"""POST /venues/{id}/ingest + GET /jobs/{id} integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from axis.auth.passwords import hash_password
from axis.db.models import Role, RoleAssignment, User, Venue
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.ids import new_id

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app(applied_db_url: str) -> FastAPI:
    from axis.db.base import dispose_engine, get_session_factory
    from axis.main import create_app

    await dispose_engine()
    factory = get_session_factory()
    async with factory() as session:
        await seed_iam(session)
        await seed_taxonomy(session)
        await session.commit()
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_editor_token(c: AsyncClient, email: str) -> str:
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
        rr = (await session.execute(select(Role).where(Role.name == "editor"))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
    return str(
        (await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})).json()[
            "access_token"
        ]
    )


async def _seed_venue(name: str) -> UUID:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        v = Venue(id=new_id(), name=name, venue_type="hotel", country_code="DE")
        session.add(v)
        await session.commit()
        return v.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submit_returns_202_and_job_id(client: AsyncClient) -> None:
    vid = await _seed_venue("submit_1")
    async with client as c:
        token = await _make_editor_token(c, "submitter@example.com")
        resp = await c.post(
            f"/api/v1/venues/{vid}/ingest",
            json={"text": "some text"},
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "abc-123",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["created"] is True
        assert body["status"] == "queued"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_replay_returns_same_job(client: AsyncClient) -> None:
    vid = await _seed_venue("submit_2")
    async with client as c:
        token = await _make_editor_token(c, "replay@example.com")
        first = (
            await c.post(
                f"/api/v1/venues/{vid}/ingest",
                json={"text": "same body"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "key-same",
                },
            )
        ).json()
        second = (
            await c.post(
                f"/api/v1/venues/{vid}/ingest",
                json={"text": "same body"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "key-same",
                },
            )
        ).json()
        assert first["job_id"] == second["job_id"]
        assert second["created"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_conflict_is_409(client: AsyncClient) -> None:
    vid = await _seed_venue("submit_3")
    async with client as c:
        token = await _make_editor_token(c, "conflict@example.com")
        await c.post(
            f"/api/v1/venues/{vid}/ingest",
            json={"text": "body one"},
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "key-conflict",
            },
        )
        again = await c.post(
            f"/api/v1/venues/{vid}/ingest",
            json={"text": "body TWO"},  # different content, same key
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "key-conflict",
            },
        )
        assert again.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_idempotency_key_is_400(client: AsyncClient) -> None:
    vid = await _seed_venue("submit_4")
    async with client as c:
        token = await _make_editor_token(c, "noidemp@example.com")
        resp = await c.post(
            f"/api/v1/venues/{vid}/ingest",
            json={"text": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_venue_is_404(client: AsyncClient) -> None:
    async with client as c:
        token = await _make_editor_token(c, "nv@example.com")
        bogus = "01900000-0000-7000-8000-deadbeefcafe"
        resp = await c.post(
            f"/api/v1/venues/{bogus}/ingest",
            json={"text": "x"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "k-nv"},
        )
        assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_status_endpoint(client: AsyncClient) -> None:
    vid = await _seed_venue("status_1")
    async with client as c:
        token = await _make_editor_token(c, "status@example.com")
        submit = await c.post(
            f"/api/v1/venues/{vid}/ingest",
            json={"text": "status check"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "k-status"},
        )
        jid = submit.json()["job_id"]
        resp = await c.get(f"/api/v1/jobs/{jid}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == jid
        assert body["status"] == "queued"
        assert body["dlq_present"] is False
