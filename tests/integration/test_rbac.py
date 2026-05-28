"""RBAC enforcement — ``require_scope`` is the only gate.

The tests mount a tiny protected route on the real app and verify that
the dependency factory rejects missing scopes and accepts present ones,
across both JWT and API-key principals.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import (
    AsyncIterator,  # noqa: TC003 -- pytest_asyncio needs runtime visibility on fixture return types
)
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from axis.api.v1.deps import require_scope
from axis.auth.passwords import hash_password
from axis.db.models import ApiKey, Role, RoleAssignment, User
from axis.db.seed_iam import seed_iam
from axis.ids import new_id

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app_protected(applied_db_url: str) -> AsyncIterator[FastAPI]:
    from axis.db.base import dispose_engine, get_session_factory
    from axis.main import create_app

    await dispose_engine()
    factory = get_session_factory()
    async with factory() as session:
        await seed_iam(session)
        await session.commit()

    app = create_app()

    @app.get(
        "/test/venues-read",
        dependencies=[Depends(require_scope("venue:read"))],
    )
    async def _vr() -> dict[str, bool]:
        return {"ok": True}

    @app.get(
        "/test/taxonomy-admin",
        dependencies=[Depends(require_scope("taxonomy:admin"))],
    )
    async def _ta() -> dict[str, bool]:
        return {"ok": True}

    yield app
    from axis.db.base import dispose_engine as _dispose

    await _dispose()


@pytest_asyncio.fixture
async def client(app_protected: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_protected), base_url="http://test")


async def _login(client: AsyncClient, email: str, password: str) -> str:
    body = (
        await client.post("/api/v1/auth/token", data={"username": email, "password": password})
    ).json()
    return str(body["access_token"])


async def _provision_user(*, email: str, role_name: str) -> None:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        user_id = new_id()
        session.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password("pw"),
                is_active=True,
            )
        )
        await session.flush()
        role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
        session.add(RoleAssignment(user_id=user_id, role_id=role.id))
        await session.commit()


async def _mint_api_key(*, scopes: list[str], name: str) -> str:
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    raw = secrets.token_urlsafe(24)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    async with factory() as session:
        session.add(
            ApiKey(
                id=new_id(),
                key_hash=key_hash,
                prefix=raw[:8],
                name=name,
                scopes=scopes,
            )
        )
        await session.commit()
    return raw


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_credentials_is_401(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/test/venues-read")
        assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_present_scope_passes(client: AsyncClient) -> None:
    await _provision_user(email="reader@example.com", role_name="reader")
    async with client as c:
        token = await _login(c, "reader@example.com", "pw")
        resp = await c.get("/test/venues-read", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_scope_is_403(client: AsyncClient) -> None:
    await _provision_user(email="r2@example.com", role_name="reader")
    async with client as c:
        token = await _login(c, "r2@example.com", "pw")
        resp = await c.get(
            "/test/taxonomy-admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "taxonomy:admin" in resp.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_principal_with_scope_passes(client: AsyncClient) -> None:
    raw = await _mint_api_key(scopes=["venue:read"], name="acme")
    async with client as c:
        resp = await c.get("/test/venues-read", headers={"X-API-Key": raw})
        assert resp.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_principal_without_scope_is_403(client: AsyncClient) -> None:
    raw = await _mint_api_key(scopes=["venue:read"], name="acme2")
    async with client as c:
        resp = await c.get("/test/taxonomy-admin", headers={"X-API-Key": raw})
        assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revoked_api_key_is_401(client: AsyncClient) -> None:
    from datetime import UTC, datetime

    from axis.db.base import get_session_factory

    raw = await _mint_api_key(scopes=["venue:read"], name="revoked")
    factory = get_session_factory()
    async with factory() as session:
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        row = (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        ).scalar_one()
        row.revoked_at = datetime.now(UTC)
        await session.commit()
    async with client as c:
        resp = await c.get("/test/venues-read", headers={"X-API-Key": raw})
        assert resp.status_code == 401
