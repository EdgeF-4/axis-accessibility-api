"""End-to-end auth flows over the FastAPI app — login, refresh rotation, reuse.

These tests run against a real Postgres (testcontainers) and a real
ASGI app (httpx + ASGITransport). No mocks; the path that runs in
production is the path that runs here.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 -- pytest_asyncio needs runtime visibility on fixture return types
)
from typing import TYPE_CHECKING, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from axis.auth.passwords import hash_password
from axis.db.models import Role, RoleAssignment, User
from axis.db.seed_iam import seed_iam
from axis.ids import new_id

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app_with_seed(applied_db_url: str) -> AsyncIterator[FastAPI]:
    # applied_db_url ensures schema + AXIS_DB_DSN env are in place.
    from axis.db.base import dispose_engine, get_session_factory
    from axis.main import create_app

    await dispose_engine()  # force re-create against the (possibly changed) DSN
    factory = get_session_factory()
    async with factory() as session:
        await seed_iam(session)
        await session.commit()
    app = create_app()
    yield app
    from axis.db.base import dispose_engine as _dispose

    await _dispose()


@pytest_asyncio.fixture
async def client(app_with_seed: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app_with_seed)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_user(*, email: str, password: str, role_name: str = "editor") -> UUID:
    """Insert a user with one role, commit, and return the new user id."""
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        user_id = new_id()
        session.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                is_active=True,
            )
        )
        await session.flush()
        role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
        session.add(RoleAssignment(user_id=user_id, role_id=role.id))
        await session.commit()
        return user_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_issues_pair(client: AsyncClient) -> None:
    await _make_user(email="alice@example.com", password="hunter22")
    async with client as c:
        resp = await c.post(
            "/api/v1/auth/token",
            data={"username": "alice@example.com", "password": "hunter22"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["refresh_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wrong_password_returns_401(client: AsyncClient) -> None:
    await _make_user(email="bob@example.com", password="right")
    async with client as c:
        resp = await c.post(
            "/api/v1/auth/token",
            data={"username": "bob@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_old(client: AsyncClient) -> None:
    await _make_user(email="carol@example.com", password="pw")
    async with client as c:
        first = (
            await c.post(
                "/api/v1/auth/token",
                data={"username": "carol@example.com", "password": "pw"},
            )
        ).json()
        # Rotate once — must succeed.
        rotated = await c.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first["refresh_token"]},
        )
        assert rotated.status_code == 200, rotated.text
        rotated_body = rotated.json()
        assert rotated_body["refresh_token"] != first["refresh_token"]

        # Replay the old token — must fail AND revoke the family.
        replay = await c.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first["refresh_token"]},
        )
        assert replay.status_code == 401
        assert "reused" in replay.json()["detail"].lower()

        # The newly-rotated token is now also unusable.
        after_family_revoke = await c.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": rotated_body["refresh_token"]},
        )
        assert after_family_revoke.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_refresh_token_rejected(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
        assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_access_token_carries_user_scopes(client: AsyncClient) -> None:
    # editor role grants {venue:read, venue:write, ingest:run, review:resolve}
    await _make_user(email="dave@example.com", password="pw", role_name="editor")
    async with client as c:
        body = (
            await c.post(
                "/api/v1/auth/token",
                data={"username": "dave@example.com", "password": "pw"},
            )
        ).json()
    # Decode the access token client-side just for the assertion.
    from axis.auth.jwt import decode_access_token

    claims = decode_access_token(body["access_token"])
    scopes = set(cast("list[str]", claims.get("scopes") or []))
    assert scopes == {"venue:read", "venue:write", "ingest:run", "review:resolve"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_revokes_family(client: AsyncClient) -> None:
    await _make_user(email="erin@example.com", password="pw")
    async with client as c:
        login = (
            await c.post(
                "/api/v1/auth/token",
                data={"username": "erin@example.com", "password": "pw"},
            )
        ).json()
        access = login["access_token"]
        refresh = login["refresh_token"]
        logout = await c.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert logout.status_code == 204
        # After logout the refresh family is dead.
        attempt = await c.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert attempt.status_code == 401
