"""End-to-end ingestion pipeline against a real Postgres + FakeExtractor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import select

from axis.db.models import Datapoint, DLQEntry, IngestionJob, ReviewItem, Venue
from axis.db.models.enums import JobStatus, Provenance, ReviewStatus
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.extraction import CandidateDatapoint
from axis.extraction.fake import FakeExtractor
from axis.ids import new_id
from axis.ingestion import run_ingestion_job
from axis.ingestion.idempotency import submit_ingestion
from axis.ingestion.retry import RetryableProviderError

if TYPE_CHECKING:
    from uuid import UUID


@pytest_asyncio.fixture
async def seeded(applied_db_url: str) -> None:
    from axis.db.base import dispose_engine, get_session_factory

    await dispose_engine()
    factory = get_session_factory()
    async with factory() as session:
        await seed_iam(session)
        await seed_taxonomy(session)
        await session.commit()


async def _make_venue(name: str) -> UUID:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        v = Venue(id=new_id(), name=name, venue_type="hotel", country_code="DE")
        session.add(v)
        await session.commit()
        return v.id


async def _enqueue_job(venue_id: UUID, *, idempotency_key: str, text: str) -> UUID:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        job, _ = await submit_ingestion(
            session,
            venue_id=venue_id,
            idempotency_key=idempotency_key,
            payload={"text": text, "source_url": None},
        )
        await session.commit()
        return job.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_persists_high_confidence_datapoint(seeded: None) -> None:
    from axis.db.base import get_session_factory

    venue_id = await _make_venue("Hotel Apex")
    job_id = await _enqueue_job(
        venue_id, idempotency_key="k-high", text="step-free entrance throughout"
    )
    fake = FakeExtractor(
        responses={
            "step-free": [
                CandidateDatapoint(
                    attribute_key="step_free_entrance",
                    value=True,
                    confidence=0.95,
                    evidence_text="step-free entrance throughout",
                )
            ]
        }
    )
    summary = await run_ingestion_job(job_id, provider=fake)
    assert summary == {
        "persisted": 1,
        "reviewed": 0,
        "dropped": 0,
        "conflicts": 0,
        "unknown": 0,
        "embedded": 1,
    }
    async with get_session_factory()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        dp = (
            (await session.execute(select(Datapoint).where(Datapoint.venue_id == venue_id)))
            .scalars()
            .all()
        )
        assert len(dp) == 1
        assert dp[0].value_bool is True
        assert dp[0].provenance is Provenance.AI_EXTRACTION


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_routes_low_confidence_to_review(seeded: None) -> None:
    from axis.db.base import get_session_factory

    venue_id = await _make_venue("Hotel Maybe")
    job_id = await _enqueue_job(
        venue_id, idempotency_key="k-mid", text="some loose claim about a ramp"
    )
    fake = FakeExtractor(
        responses={
            "ramp": [CandidateDatapoint(attribute_key="ramp_present", value=True, confidence=0.6)]
        }
    )
    summary = await run_ingestion_job(job_id, provider=fake)
    assert summary["persisted"] == 0
    assert summary["reviewed"] == 1
    async with get_session_factory()() as session:
        reviews: list[ReviewItem] = list(
            (await session.execute(select(ReviewItem).where(ReviewItem.venue_id == venue_id)))
            .scalars()
            .all()
        )
        assert len(reviews) == 1
        assert reviews[0].status is ReviewStatus.PENDING
        assert reviews[0].candidate["unknown_attribute"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_drops_below_review_threshold(seeded: None) -> None:
    venue_id = await _make_venue("Hotel Wild")
    job_id = await _enqueue_job(venue_id, idempotency_key="k-low", text="ramp ambiguity")
    fake = FakeExtractor(
        responses={
            "ramp": [CandidateDatapoint(attribute_key="ramp_present", value=True, confidence=0.2)]
        }
    )
    summary = await run_ingestion_job(job_id, provider=fake)
    assert summary == {
        "persisted": 0,
        "reviewed": 0,
        "dropped": 1,
        "conflicts": 0,
        "unknown": 0,
        "embedded": 0,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_attribute_flagged_into_review_queue(seeded: None) -> None:
    from axis.db.base import get_session_factory
    from axis.extraction.fake import FakeExtractor as Fk
    from axis.extraction.schemas import UnknownAttribute

    venue_id = await _make_venue("Hotel Unknown")
    job_id = await _enqueue_job(
        venue_id, idempotency_key="k-unknown", text="claims an esoteric feature"
    )
    fake = Fk(
        responses={"esoteric": []},
        unknowns=[UnknownAttribute(attribute_key="zero_gravity_room", value=True, confidence=0.99)],
    )
    summary = await run_ingestion_job(job_id, provider=fake)
    assert summary["unknown"] == 1
    async with get_session_factory()() as session:
        reviews: list[ReviewItem] = list(
            (await session.execute(select(ReviewItem).where(ReviewItem.venue_id == venue_id)))
            .scalars()
            .all()
        )
        assert len(reviews) == 1
        assert reviews[0].candidate["unknown_attribute"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_supersedes_lower_confidence_same_provenance(
    seeded: None,
) -> None:
    from axis.db.base import get_session_factory

    venue_id = await _make_venue("Hotel Twice")
    # First job: confidence 0.85, value=True
    job1 = await _enqueue_job(venue_id, idempotency_key="k1", text="step-free entrance one")
    fake1 = FakeExtractor(
        responses={
            "step-free": [
                CandidateDatapoint(attribute_key="step_free_entrance", value=True, confidence=0.85)
            ]
        }
    )
    await run_ingestion_job(job1, provider=fake1)

    # Second job: same provenance, different value -> supersedes
    job2 = await _enqueue_job(
        venue_id, idempotency_key="k2", text="step-free entrance two but disputed"
    )
    fake2 = FakeExtractor(
        responses={
            "step-free": [
                CandidateDatapoint(attribute_key="step_free_entrance", value=False, confidence=0.9)
            ]
        }
    )
    summary = await run_ingestion_job(job2, provider=fake2)
    assert summary["persisted"] == 1
    async with get_session_factory()() as session:
        dps = (
            (await session.execute(select(Datapoint).where(Datapoint.venue_id == venue_id)))
            .scalars()
            .all()
        )
        # Two rows: the old one (superseded) and the new live one.
        assert len(dps) == 2
        live = [d for d in dps if d.superseded_by_id is None]
        assert len(live) == 1
        assert live[0].value_bool is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_exhaustion_dlqs_job(seeded: None) -> None:
    from axis.db.base import get_session_factory

    venue_id = await _make_venue("Hotel Doomed")
    job_id = await _enqueue_job(venue_id, idempotency_key="k-dlq", text="anything")
    fake = FakeExtractor(raise_with=RetryableProviderError)
    with pytest.raises(RetryableProviderError):
        await run_ingestion_job(job_id, provider=fake)
    async with get_session_factory()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        assert job.status is JobStatus.DLQ
        dlq = (
            await session.execute(select(DLQEntry).where(DLQEntry.job_id == job_id))
        ).scalar_one()
        assert "provider failed" in dlq.terminal_error
