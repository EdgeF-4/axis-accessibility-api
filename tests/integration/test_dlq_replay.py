"""DLQ replay endpoint — reset a dead-lettered job to QUEUED."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 -- pytest_asyncio needs runtime visibility on fixture return types
)
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from axis.auth.passwords import hash_password
from axis.db.models import IngestionJob, Role, RoleAssignment, User, Venue
from axis.db.models.enums import JobStatus
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.extraction.fake import FakeExtractor
from axis.ids import new_id
from axis.ingestion import run_ingestion_job
from axis.ingestion.idempotency import submit_ingestion
from axis.ingestion.retry import RetryableProviderError

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app(applied_db_url: str) -> AsyncIterator[FastAPI]:
    from axis.db.base import dispose_engine, get_session_factory
    from axis.main import create_app

    await dispose_engine()
    factory = get_session_factory()
    async with factory() as session:
        await seed_iam(session)
        await seed_taxonomy(session)
        await session.commit()
    app = create_app()
    yield app
    from axis.db.base import dispose_engine as _dispose

    await _dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _editor_token(c: AsyncClient, email: str) -> str:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        uid = new_id()
        session.add(User(id=uid, email=email, password_hash=hash_password("pw"), is_active=True))
        await session.flush()
        rr = (await session.execute(select(Role).where(Role.name == "editor"))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
    return str(
        (await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})).json()[
            "access_token"
        ]
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replay_known_dlq_job(client: AsyncClient) -> None:
    """A DLQ'd job replays back to QUEUED."""
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    # 1. seed venue + job
    async with factory() as session:
        v = Venue(id=new_id(), name="DLQ Hotel", venue_type="hotel", country_code="DE")
        session.add(v)
        await session.flush()
        venue_id = v.id
        job, _ = await submit_ingestion(
            session,
            venue_id=venue_id,
            idempotency_key="k-dlq-replay",
            payload={"text": "anything", "source_url": None},
        )
        job_id = job.id
        await session.commit()
    # 2. force DLQ
    fake = FakeExtractor(raise_with=RetryableProviderError)
    with pytest.raises(RetryableProviderError):
        await run_ingestion_job(job_id, provider=fake)
    # 3. confirm DLQ state
    async with factory() as session:
        before = await session.get(IngestionJob, job_id)
        assert before is not None
        assert before.status is JobStatus.DLQ
        assert before.attempts > 0
    # 4. replay via API
    async with client as c:
        token = await _editor_token(c, f"dq-dlq-{new_id()}@example.com")
        resp = await c.post(
            f"/api/v1/dlq/{job_id}/replay",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_status"] == "queued"
    # 5. job is now QUEUED with attempts=0
    async with factory() as session:
        after = await session.get(IngestionJob, job_id)
        assert after is not None
        assert after.status is JobStatus.QUEUED
        assert after.attempts == 0
        assert after.started_at is None
        assert after.finished_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replay_unknown_job_is_404(client: AsyncClient) -> None:
    async with client as c:
        token = await _editor_token(c, f"dq-miss-{new_id()}@example.com")
        bogus = "01900000-0000-7000-8000-deadbeefcafe"
        resp = await c.post(
            f"/api/v1/dlq/{bogus}/replay",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
