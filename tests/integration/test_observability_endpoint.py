"""``/metrics`` exposition + per-request observability behaviour."""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003 -- pytest_asyncio runtime requirement
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app(applied_db_url: str) -> AsyncIterator[FastAPI]:
    from axis.db.base import dispose_engine
    from axis.main import create_app

    await dispose_engine()
    app = create_app()
    yield app
    await dispose_engine()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(client: AsyncClient) -> None:
    async with client as c:
        # Hit a known route first so we have something interesting to expose.
        await c.get("/api/v1/healthz")
        resp = await c.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        assert "axis_http_requests_total" in body
        assert "axis_http_request_duration_seconds" in body
        # The healthz hit must have produced at least one count.
        assert 'path="/api/v1/healthz"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_id_round_trips(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/healthz", headers={"X-Request-ID": "rid-fixed-12345"})
        assert resp.headers.get("X-Request-ID") == "rid-fixed-12345"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_request_id_minted_when_absent(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/healthz")
        rid = resp.headers.get("X-Request-ID", "")
        assert rid  # non-empty
        assert len(rid) >= 16  # uuid4().hex is 32, but defensive
