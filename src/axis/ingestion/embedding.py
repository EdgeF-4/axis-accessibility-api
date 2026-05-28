"""Embedding stage of the ingestion pipeline.

For every datapoint that the persist stage just wrote (live + ai_extraction
provenance, ingestion_job_id pointing at the current job), we generate a
short natural-language summary and embed it. The result is stored in
``datapoints.embedding``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from axis.db.models import Datapoint, TaxonomyAttribute

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from axis.embeddings.provider import EmbeddingProvider


def render_embedding_text(*, attribute_label: str, value: object, evidence: str | None) -> str:
    """Build the string we embed for ``(attribute, value)``.

    Stable function — used by the pipeline AND by the semantic-search
    endpoint when a user query is rendered against the same prompt shape.
    """
    parts = [attribute_label, "=", str(value)]
    if evidence:
        parts.append(f"({evidence})")
    return " ".join(parts)


async def embed_job_datapoints(
    session: AsyncSession,
    *,
    job_id: UUID,
    provider: EmbeddingProvider,
) -> int:
    """Embed every datapoint produced by ``job_id`` that still lacks one.

    Returns the count of datapoints embedded. Idempotent: re-running this
    function on the same job is a no-op once embeddings are present.
    """
    stmt = (
        select(Datapoint, TaxonomyAttribute)
        .join(TaxonomyAttribute, TaxonomyAttribute.id == Datapoint.attribute_id)
        .where(
            Datapoint.ingestion_job_id == job_id,
            Datapoint.embedding.is_(None),
        )
    )
    rows = list((await session.execute(stmt)).all())
    if not rows:
        return 0

    texts: list[str] = []
    targets: list[Datapoint] = []
    for dp, attr in rows:
        value = (
            dp.value_bool
            if dp.value_bool is not None
            else (float(dp.value_numeric) if dp.value_numeric is not None else dp.value_enum)
        )
        evidence_text = None
        if isinstance(dp.evidence, dict):
            ev = dp.evidence.get("text")
            evidence_text = ev if isinstance(ev, str) else None
        texts.append(
            render_embedding_text(
                attribute_label=attr.label,
                value=value,
                evidence=evidence_text,
            )
        )
        targets.append(dp)

    vectors = await provider.embed(texts)
    if len(vectors) != len(targets):
        raise RuntimeError(
            f"embedding provider returned {len(vectors)} vectors for {len(targets)} inputs"
        )
    for dp, vec in zip(targets, vectors, strict=True):
        dp.embedding = vec
    await session.flush()
    return len(targets)


def all_texts_for(datapoint_summaries: Iterable[tuple[str, object, str | None]]) -> list[str]:
    """Pure helper used by tests to assemble the same texts the stage would."""
    return [
        render_embedding_text(attribute_label=label, value=value, evidence=ev)
        for (label, value, ev) in datapoint_summaries
    ]
