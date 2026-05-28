"""Health endpoints over the live ASGI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app(applied_db_url: str) -> FastAPI:
    from axis.db.base import dispose_engine
    from axis.main import create_app

    await dispose_engine()
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_healthz_is_cheap_200(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readyz_reports_db_alembic_head(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/readyz")
        body = resp.json()
        # DB check must report alembic head; redis is optional in this run.
        assert "db" in body["checks"]
        assert body["checks"]["db"].startswith("ok")
