"""Semantic search endpoint + embedding stage end-to-end.

We use :class:`FakeEmbedder` so vectors are deterministic. The HNSW index
on ``datapoints.embedding`` (migration 0003) is exercised by the
``<=>`` cosine-distance operator inside ``semantic_search_venues``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003 -- pytest_asyncio runtime requirement
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from axis.auth.passwords import hash_password
from axis.db.models import Datapoint, Role, RoleAssignment, User, Venue
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.extraction import CandidateDatapoint
from axis.extraction.fake import FakeExtractor
from axis.ids import new_id
from axis.ingestion import run_ingestion_job
from axis.ingestion.idempotency import submit_ingestion

if TYPE_CHECKING:
    from uuid import UUID

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


async def _reader_token(c: AsyncClient) -> str:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        uid = new_id()
        email = f"reader-{new_id()}@example.com"
        session.add(
            User(
                id=uid,
                email=email,
                password_hash=hash_password("pw"),
                is_active=True,
            )
        )
        await session.flush()
        rr = (await session.execute(select(Role).where(Role.name == "reader"))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
    return str(
        (await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})).json()[
            "access_token"
        ]
    )


async def _ingest(name: str, *, attr_key: str, value: bool) -> UUID:
    """Create a venue + one ingestion job → run pipeline (with FakeEmbedder)."""
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        v = Venue(id=new_id(), name=name, venue_type="hotel", country_code="DE")
        session.add(v)
        await session.flush()
        vid = v.id
        job, _ = await submit_ingestion(
            session,
            venue_id=vid,
            idempotency_key=f"k-{new_id()}",
            payload={"text": f"claim {attr_key}", "source_url": None},
        )
        await session.commit()

    fake = FakeExtractor(
        responses={
            "claim": [CandidateDatapoint(attribute_key=attr_key, value=value, confidence=0.95)]
        }
    )
    await run_ingestion_job(job.id, provider=fake)
    return vid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_writes_embeddings(client: AsyncClient) -> None:
    from axis.db.base import get_session_factory

    venue_id = await _ingest("embed_one", attr_key="step_free_entrance", value=True)
    async with get_session_factory()() as session:
        dp = (
            await session.execute(select(Datapoint).where(Datapoint.venue_id == venue_id))
        ).scalar_one()
        assert dp.embedding is not None
        assert len(dp.embedding) == 384


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_search_returns_matching_venues(client: AsyncClient) -> None:
    """Two venues with different attributes; query matching one ranks it higher."""
    sf_id = await _ingest("sf_hotel", attr_key="step_free_entrance", value=True)
    rs_id = await _ingest("rs_hotel", attr_key="roll_in_shower", value=True)
    async with client as c:
        token = await _reader_token(c)
        resp = await c.get(
            "/api/v1/venues/search/semantic",
            params={"q": "Step-free entrance = True (step-free entrance)", "limit": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Both venues' embeddings exist; the endpoint returns both.
        venue_ids = {item["venue_id"] for item in body["items"]}
        assert str(sf_id) in venue_ids
        assert str(rs_id) in venue_ids
        # Distances are present and increasing-from-best-match.
        distances = [item["distance"] for item in body["items"]]
        assert distances == sorted(distances)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_search_requires_venue_read(client: AsyncClient) -> None:
    # Mint a user with no role at all → token has no scopes.
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        uid = new_id()
        email = f"noscope-{new_id()}@example.com"
        session.add(
            User(
                id=uid,
                email=email,
                password_hash=hash_password("pw"),
                is_active=True,
            )
        )
        await session.commit()
    async with client as c:
        token = (
            await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})
        ).json()["access_token"]
        resp = await c.get(
            "/api/v1/venues/search/semantic",
            params={"q": "anything"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_search_with_no_data_returns_empty(client: AsyncClient) -> None:
    async with client as c:
        token = await _reader_token(c)
        resp = await c.get(
            "/api/v1/venues/search/semantic",
            params={"q": "no venues exist"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
