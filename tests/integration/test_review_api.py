"""Human-in-the-loop review queue + resolution flows."""

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
from axis.db.models import (
    Datapoint,
    Role,
    RoleAssignment,
    User,
    Venue,
)
from axis.db.models.enums import Provenance
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.extraction import CandidateDatapoint
from axis.extraction.fake import FakeExtractor
from axis.extraction.schemas import UnknownAttribute
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


async def _token(c: AsyncClient, email: str, role_name: str = "editor") -> str:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        uid = new_id()
        session.add(
            User(
                id=uid,
                email=email,
                password_hash=hash_password("pw"),
                is_active=True,
            )
        )
        await session.flush()
        rr = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
    return str(
        (await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})).json()[
            "access_token"
        ]
    )


async def _seed_review_item(
    *,
    confidence: float,
    text: str = "ambiguous claim",
    name: str = "Hotel Review",
    cand_key: str = "ramp_present",
    cand_value: bool | float | str = True,
    unknowns: list[UnknownAttribute] | None = None,
) -> tuple[UUID, UUID]:
    """Create a venue and submit a single ingestion that produces ONE review item.

    Returns ``(venue_id, review_item_id)``.
    """
    from axis.db.base import get_session_factory
    from axis.db.models import ReviewItem

    factory = get_session_factory()
    async with factory() as session:
        venue = Venue(id=new_id(), name=name, venue_type="hotel", country_code="DE")
        session.add(venue)
        await session.flush()
        venue_id = venue.id
        job, _ = await submit_ingestion(
            session,
            venue_id=venue_id,
            idempotency_key=f"k-{new_id()}",
            payload={"text": text, "source_url": None},
        )
        await session.commit()

    fake = FakeExtractor(
        responses={
            "claim": [
                CandidateDatapoint(
                    attribute_key=cand_key,
                    value=cand_value,
                    confidence=confidence,
                )
            ]
        }
        if unknowns is None
        else {"claim": []},
        unknowns=unknowns or [],
    )
    await run_ingestion_job(job.id, provider=fake)

    factory = get_session_factory()
    async with factory() as session:
        ri = (
            await session.execute(select(ReviewItem).where(ReviewItem.venue_id == venue_id))
        ).scalar_one()
        return venue_id, ri.id


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_defaults_to_pending(client: AsyncClient) -> None:
    venue_id, _ = await _seed_review_item(confidence=0.6, text="claim ramp here")
    async with client as c:
        token = await _token(c, f"rv-list_a-{new_id()}@example.com", role_name="reviewer")
        resp = await c.get(
            "/api/v1/review-queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert any(item["venue_id"] == str(venue_id) for item in body["items"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_requires_review_scope(client: AsyncClient) -> None:
    async with client as c:
        token = await _token(c, f"rv-reader_a-{new_id()}@example.com", role_name="reader")
        resp = await c.get(
            "/api/v1/review-queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Resolve actions
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_accept_writes_human_datapoint(client: AsyncClient) -> None:
    from axis.db.base import get_session_factory

    venue_id, review_id = await _seed_review_item(confidence=0.6, text="claim ramp here")
    async with client as c:
        token = await _token(c, f"rv-acc-{new_id()}@example.com", role_name="reviewer")
        resp = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "accept"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["datapoint_id"] is not None
    async with get_session_factory()() as session:
        dps = list(
            (await session.execute(select(Datapoint).where(Datapoint.venue_id == venue_id)))
            .scalars()
            .all()
        )
        humans = [d for d in dps if d.provenance is Provenance.HUMAN]
        assert len(humans) == 1
        assert humans[0].value_bool is True
        assert humans[0].verified_by is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_does_not_write_datapoint(client: AsyncClient) -> None:
    from axis.db.base import get_session_factory

    venue_id, review_id = await _seed_review_item(
        confidence=0.6, text="claim ramp here", name="Hotel Reject"
    )
    async with client as c:
        token = await _token(c, f"rv-rej-{new_id()}@example.com", role_name="reviewer")
        resp = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "reject"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["datapoint_id"] is None
    async with get_session_factory()() as session:
        humans = (
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
        assert humans == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edit_writes_modified_value(client: AsyncClient) -> None:
    from axis.db.base import get_session_factory

    venue_id, review_id = await _seed_review_item(
        confidence=0.6, text="claim ramp here", name="Hotel Edit"
    )
    async with client as c:
        token = await _token(c, f"rv-edit-{new_id()}@example.com", role_name="reviewer")
        resp = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "edit", "value": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "edited"
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
        assert len(humans) == 1
        assert humans[0].value_bool is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_attribute_can_only_be_rejected(client: AsyncClient) -> None:
    venue_id, review_id = await _seed_review_item(
        confidence=0.6,
        text="claim a feature",
        name="Hotel Unknown Review",
        unknowns=[UnknownAttribute(attribute_key="bogus_attr", value=True, confidence=0.9)],
    )
    assert venue_id is not None
    async with client as c:
        token = await _token(c, f"rv-unk-{new_id()}@example.com", role_name="reviewer")
        # accept must be refused (no taxonomy attribute to map to)
        accept = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "accept"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert accept.status_code == 400
        # reject is allowed
        reject = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "reject"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reject.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_double_resolve_is_409(client: AsyncClient) -> None:
    _, review_id = await _seed_review_item(
        confidence=0.6, text="claim ramp here", name="Hotel Twice"
    )
    async with client as c:
        token = await _token(c, f"rv-twice-{new_id()}@example.com", role_name="reviewer")
        await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "reject"},
            headers={"Authorization": f"Bearer {token}"},
        )
        again = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "reject"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert again.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_review_id_is_404(client: AsyncClient) -> None:
    async with client as c:
        token = await _token(c, f"rv-miss-{new_id()}@example.com", role_name="reviewer")
        bogus = "01900000-0000-7000-8000-deadbeefcafe"
        resp = await c.post(
            f"/api/v1/review-queue/{bogus}/resolve",
            json={"action": "reject"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edit_without_value_is_400(client: AsyncClient) -> None:
    _, review_id = await _seed_review_item(
        confidence=0.6, text="claim ramp here", name="Hotel NoValue"
    )
    async with client as c:
        token = await _token(c, f"rv-nov-{new_id()}@example.com", role_name="reviewer")
        resp = await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "edit"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_human_supersedes_existing_ai_datapoint(client: AsyncClient) -> None:
    """After human resolution, the AI-provenance live row gets a new HUMAN sibling."""
    from axis.db.base import get_session_factory

    venue_id, review_id = await _seed_review_item(
        confidence=0.6, text="claim ramp here", name="Hotel AIThenHuman"
    )
    # Also persist an AI-confident datapoint for the same attribute via the pipeline
    async with get_session_factory()() as session:
        job, _ = await submit_ingestion(
            session,
            venue_id=venue_id,
            idempotency_key="k-ai-confident",
            payload={"text": "claim ramp confidently", "source_url": None},
        )
        await session.commit()
    fake = FakeExtractor(
        responses={
            "claim": [CandidateDatapoint(attribute_key="ramp_present", value=True, confidence=0.95)]
        }
    )
    await run_ingestion_job(job.id, provider=fake)

    # Now resolve the (separate) review item with HUMAN value=False
    async with client as c:
        token = await _token(c, f"rv-human-{new_id()}@example.com", role_name="reviewer")
        await c.post(
            f"/api/v1/review-queue/{review_id}/resolve",
            json={"action": "edit", "value": False},
            headers={"Authorization": f"Bearer {token}"},
        )
    async with get_session_factory()() as session:
        dps = list(
            (await session.execute(select(Datapoint).where(Datapoint.venue_id == venue_id)))
            .scalars()
            .all()
        )
        # We expect AI live + HUMAN live (different provenances) — both present
        # because partial-unique is per provenance.
        provenances = {d.provenance for d in dps if d.superseded_by_id is None}
        assert Provenance.AI_EXTRACTION in provenances
        assert Provenance.HUMAN in provenances
