"""Top-level orchestrator for an ingestion job.

Public entry point: :func:`run_ingestion_job`. The ARQ task wraps this;
tests call it directly. The function is also responsible for state
transitions on the :class:`IngestionJob` row and DLQ insertion on
terminal failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from axis.config import get_settings
from axis.db.base import session_scope
from axis.db.models import (
    DLQEntry,
    IngestionJob,
    TaxonomyAttribute,
    TaxonomyCategory,
    TaxonomyVersion,
)
from axis.db.models.enums import JobStatus
from axis.embeddings.fake import FakeEmbedder
from axis.extraction.fake import FakeExtractor
from axis.extraction.provider import (
    ExtractorProvider,
    TaxonomyAttributeSpec,
    TaxonomySnapshot,
)
from axis.ids import new_id
from axis.ingestion.circuit import CircuitBreaker, CircuitOpenError
from axis.ingestion.embedding import embed_job_datapoints
from axis.ingestion.persist import persist_extraction
from axis.ingestion.retry import RetryableProviderError, with_retry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from axis.embeddings.provider import EmbeddingProvider


async def _current_taxonomy(session: AsyncSession) -> TaxonomySnapshot:
    """Build the immutable taxonomy snapshot the extractor receives."""
    tv = (
        await session.execute(
            select(TaxonomyVersion).order_by(TaxonomyVersion.published_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if tv is None:
        return TaxonomySnapshot(version="", attributes=())
    rows = (
        await session.execute(
            select(TaxonomyAttribute, TaxonomyCategory)
            .join(TaxonomyCategory, TaxonomyCategory.id == TaxonomyAttribute.category_id)
            .where(TaxonomyAttribute.version_id == tv.id)
            .order_by(TaxonomyAttribute.key)
        )
    ).all()
    attrs = tuple(
        TaxonomyAttributeSpec(
            key=a.key,
            value_type=a.value_type,
            label=a.label,
            unit=a.unit,
            category_key=c.key,
        )
        for a, c in rows
    )
    return TaxonomySnapshot(version=tv.semver, attributes=attrs)


_DEFAULT_BREAKER: CircuitBreaker | None = None


def get_default_breaker() -> CircuitBreaker:
    """Process-local default circuit breaker (lazy + configurable via settings)."""
    global _DEFAULT_BREAKER
    if _DEFAULT_BREAKER is None:
        s = get_settings()
        _DEFAULT_BREAKER = CircuitBreaker(
            fails_to_open=s.breaker_fails_to_open,
            window_seconds=s.breaker_window_seconds,
            open_seconds=s.breaker_open_seconds,
        )
    return _DEFAULT_BREAKER


async def run_ingestion_job(
    job_id: UUID,
    *,
    provider: ExtractorProvider | None = None,
    breaker: CircuitBreaker | None = None,
    embedder: EmbeddingProvider | None = None,
) -> dict[str, int]:
    """Drive a single :class:`IngestionJob` from QUEUED to a terminal state.

    Returns the persistence summary on success (``persisted`` /
    ``reviewed`` / ``dropped`` / ``conflicts`` / ``unknown`` / ``embedded``).
    """
    s = get_settings()
    provider = provider or FakeExtractor()
    embedder = embedder or FakeEmbedder()
    breaker = breaker or get_default_breaker()

    # --- Stage 0: lift the job into RUNNING, capture inputs --------------------
    async with session_scope() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            raise ValueError(f"ingestion job {job_id} not found")
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        # job.input is JSONB; the idempotency layer wraps caller payloads
        # under the {"venue_id", "payload", "payload_hash"} shape.
        job_input: dict[str, object] = dict(job.input or {})
        venue_id_str = str(job_input.get("venue_id", ""))
        inner_payload = job_input.get("payload", {})
        if not isinstance(inner_payload, dict):
            inner_payload = {}
        text = str(inner_payload.get("text", ""))

    if not venue_id_str or not text:
        await _terminate(job_id, JobStatus.FAILED, "input missing venue_id or text")
        raise ValueError("ingestion job input malformed")
    venue_id = UUID(venue_id_str)

    # --- Stage 1: extract (with retry + breaker) -------------------------------
    async with session_scope() as session:
        taxonomy = await _current_taxonomy(session)

    async def call_provider() -> object:
        breaker.before_call()
        try:
            assert provider is not None  # noqa: S101 -- mypy narrowing only
            result = await provider.extract(text=text, taxonomy=taxonomy)
        except RetryableProviderError:
            breaker.on_failure()
            raise
        except Exception:
            breaker.on_failure()
            raise
        breaker.on_success()
        return result

    try:
        result = await with_retry(
            call_provider,
            max_attempts=s.ingest_max_attempts,
            base_seconds=s.ingest_backoff_base_seconds,
            max_seconds=s.ingest_backoff_max_seconds,
        )
    except CircuitOpenError as exc:
        await _terminate(job_id, JobStatus.FAILED, f"circuit open: {exc}")
        raise
    except RetryableProviderError as exc:
        await _dlq(job_id, payload_for_dlq=text, error=f"provider failed: {exc}")
        raise
    except Exception as exc:
        await _dlq(job_id, payload_for_dlq=text, error=f"unhandled: {exc}")
        raise

    # --- Stage 2-5: validate, route, reconcile, persist ------------------------
    async with session_scope() as session:
        summary = await persist_extraction(
            session,
            venue_id=venue_id,
            job_id=job_id,
            result=result,  # type: ignore[arg-type]
        )

    # --- Stage 6: embed (separate session so a stage-6 failure does not
    # roll back the persisted datapoints).
    async with session_scope() as session:
        embedded = await embed_job_datapoints(session, job_id=job_id, provider=embedder)
    summary["embedded"] = embedded

    async with session_scope() as session:
        finished = await session.get(IngestionJob, job_id)
        if finished is not None:
            finished.status = JobStatus.SUCCEEDED
            finished.finished_at = datetime.now(UTC)
            finished.result = {"summary": summary}

    return summary


async def _terminate(job_id: UUID, status: JobStatus, error: str) -> None:
    async with session_scope() as session:
        job = await session.get(IngestionJob, job_id)
        if job is not None:
            job.status = status
            job.error = error
            job.finished_at = datetime.now(UTC)


async def _dlq(job_id: UUID, *, payload_for_dlq: str, error: str) -> None:
    async with session_scope() as session:
        job = await session.get(IngestionJob, job_id)
        if job is not None:
            job.status = JobStatus.DLQ
            job.error = error
            job.finished_at = datetime.now(UTC)
            session.add(
                DLQEntry(
                    id=new_id(),
                    job_id=job_id,
                    payload={"text": payload_for_dlq, "input": job.input},
                    terminal_error=error,
                )
            )
