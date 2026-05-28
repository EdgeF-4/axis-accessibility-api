"""Taxonomy read endpoint."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 -- pytest_asyncio needs runtime visibility on fixture return types
)
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from axis.db.seed import seed_taxonomy

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest_asyncio.fixture
async def app(applied_db_url: str) -> AsyncIterator[FastAPI]:
    from axis.db.base import dispose_engine, get_session_factory
    from axis.main import create_app

    await dispose_engine()
    factory = get_session_factory()
    async with factory() as session:
        await seed_taxonomy(session)
        await session.commit()
    app = create_app()
    yield app
    from axis.db.base import dispose_engine as _dispose

    await _dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_taxonomy_default_is_latest(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/taxonomy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "1.0.0"
        cats = {c["key"] for c in body["categories"]}
        assert cats == {"mobility", "vision", "hearing", "cognitive", "sensory"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_taxonomy_attribute_value_types_are_well_formed(
    client: AsyncClient,
) -> None:
    async with client as c:
        body = (await c.get("/api/v1/taxonomy")).json()
    for category in body["categories"]:
        for attr in category["attributes"]:
            assert attr["value_type"] in {"bool", "numeric", "enum"}
            if attr["value_type"] != "numeric":
                assert attr["unit"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_version_is_404(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/v1/taxonomy", params={"version": "9.9.9"})
        assert resp.status_code == 404
