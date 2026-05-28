"""Extra coverage for the review surface: pagination + HUMAN-supersedes-HUMAN."""

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
from axis.db.models import Datapoint, Role, RoleAssignment, User, Venue
from axis.db.models.enums import Provenance
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


async def _reviewer_token(c: AsyncClient) -> str:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        uid = new_id()
        session.add(
            User(
                id=uid,
                email=f"rx-{new_id()}@example.com",
                password_hash=hash_password("pw"),
                is_active=True,
            )
        )
        await session.flush()
        rr = (await session.execute(select(Role).where(Role.name == "reviewer"))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
        user = await session.get(User, uid)
        assert user is not None
        login_email = user.email
    body = (
        await c.post("/api/v1/auth/token", data={"username": login_email, "password": "pw"})
    ).json()
    return str(body["access_token"])


async def _seed_pending_review(*, value: bool, name: str) -> tuple[UUID, UUID]:
    """Create one pending review item and return (venue_id, review_id)."""
    from axis.db.base import get_session_factory
    from axis.db.models import ReviewItem

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
            payload={"text": "claim ramp here", "source_url": None},
        )
        await session.commit()

    fake = FakeExtractor(
        responses={
            "claim": [CandidateDatapoint(attribute_key="ramp_present", value=value, confidence=0.6)]
        }
    )
    await run_ingestion_job(job.id, provider=fake)

    async with factory() as session:
        ri = (
            await session.execute(select(ReviewItem).where(ReviewItem.venue_id == vid))
        ).scalar_one()
        return vid, ri.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_review_list_paginates(client: AsyncClient) -> None:
    """Walk three pages of review items with limit=2, asserting no duplicates."""
    for i in range(5):
        await _seed_pending_review(value=True, name=f"pg_{i}")
    async with client as c:
        token = await _reviewer_token(c)
        first = (
            await c.get(
                "/api/v1/review-queue",
                params={"limit": 2},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        assert len(first["items"]) == 2
        assert first["next_cursor"] is not None
        second = (
            await c.get(
                "/api/v1/review-queue",
                params={"limit": 2, "cursor": first["next_cursor"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        assert len(second["items"]) == 2
        ids = {it["id"] for it in first["items"]} | {it["id"] for it in second["items"]}
        assert len(ids) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bad_review_cursor_is_400(client: AsyncClient) -> None:
    async with client as c:
        token = await _reviewer_token(c)
        resp = await c.get(
            "/api/v1/review-queue",
            params={"cursor": "not-a-cursor"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_human_accepts_supersede_each_other(client: AsyncClient) -> None:
    """Resolving a second review item for the same (venue, attribute) supersedes the first HUMAN row."""
    from axis.db.base import get_session_factory

    venue_id, first_review = await _seed_pending_review(value=True, name="seq_a")
    async with client as c:
        token = await _reviewer_token(c)
        await c.post(
            f"/api/v1/review-queue/{first_review}/resolve",
            json={"action": "accept"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Create a SECOND review item for the same venue + attribute, different value.
        from axis.db.models import ReviewItem
        from axis.extraction.fake import FakeExtractor as Fk
        from axis.extraction.schemas import CandidateDatapoint as Cand
        from axis.ingestion import run_ingestion_job as run
        from axis.ingestion.idempotency import submit_ingestion as submit

        factory = get_session_factory()
        async with factory() as session:
            job, _ = await submit(
                session,
                venue_id=venue_id,
                idempotency_key=f"k-{new_id()}",
                payload={"text": "claim ramp again", "source_url": None},
            )
            await session.commit()
        fake2 = Fk(
            responses={"claim": [Cand(attribute_key="ramp_present", value=False, confidence=0.6)]}
        )
        await run(job.id, provider=fake2)
        async with factory() as session:
            second_review = (
                await session.execute(
                    select(ReviewItem).where(
                        ReviewItem.venue_id == venue_id,
                        ReviewItem.id != first_review,
                    )
                )
            ).scalar_one()
            second_review_id = second_review.id

        # Resolve the second one with HUMAN — must SupersedeLive the first HUMAN.
        await c.post(
            f"/api/v1/review-queue/{second_review_id}/resolve",
            json={"action": "edit", "value": False},
            headers={"Authorization": f"Bearer {token}"},
        )

    async with get_session_factory()() as session:
        humans = list(
            (
                await session.execute(
                    select(Datapoint).where(
                        Datapoint.venue_id == venue_id,
                        Datapoint.provenance == Provenance.HUMAN,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Two HUMAN rows now: the old one superseded, the new one live.
        assert len(humans) == 2
        live = [d for d in humans if d.superseded_by_id is None]
        assert len(live) == 1
        assert live[0].value_bool is False
