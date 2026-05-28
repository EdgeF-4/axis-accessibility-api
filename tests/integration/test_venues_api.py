"""Venues CRUD + filter + pagination integration tests."""

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
    Provenance,
    Role,
    RoleAssignment,
    TaxonomyAttribute,
    User,
    Venue,
)
from axis.db.seed import seed_taxonomy
from axis.db.seed_iam import seed_iam
from axis.ids import new_id

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


async def _make_user_token(c: AsyncClient, email: str, role: str = "editor") -> str:
    """Provision a user and return an access token via /auth/token."""
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
        rr = (await session.execute(select(Role).where(Role.name == role))).scalar_one()
        session.add(RoleAssignment(user_id=uid, role_id=rr.id))
        await session.commit()
    resp = await c.post("/api/v1/auth/token", data={"username": email, "password": "pw"})
    return str(resp.json()["access_token"])


async def _seed_venue_with_attrs(
    *,
    name: str,
    country: str,
    attr_keys: dict[str, bool],
    lat: float | None = None,
    lon: float | None = None,
    description: str | None = None,
) -> UUID:
    """Insert a venue and (live, ai_extraction) datapoints for each attr_key=value."""
    from axis.db.base import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        v = Venue(
            id=new_id(),
            name=name,
            venue_type="hotel",
            country_code=country,
            latitude=lat,
            longitude=lon,
            description=description,
        )
        session.add(v)
        await session.flush()
        for key, value in attr_keys.items():
            attr = (
                await session.execute(select(TaxonomyAttribute).where(TaxonomyAttribute.key == key))
            ).scalar_one()
            session.add(
                Datapoint(
                    id=new_id(),
                    venue_id=v.id,
                    attribute_id=attr.id,
                    value_bool=value,
                    confidence=0.9,
                    provenance=Provenance.AI_EXTRACTION,
                )
            )
        await session.commit()
        return v.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_venue_requires_write_scope(client: AsyncClient) -> None:
    async with client as c:
        reader_token = await _make_user_token(c, "reader1@example.com", role="reader")
        resp = await c.post(
            "/api/v1/venues",
            json={"name": "X", "venue_type": "hotel", "country_code": "DE"},
            headers={"Authorization": f"Bearer {reader_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_get_round_trip(client: AsyncClient) -> None:
    async with client as c:
        token = await _make_user_token(c, "writer1@example.com", role="editor")
        body = {
            "name": "Hotel Central",
            "venue_type": "hotel",
            "country_code": "DE",
            "latitude": 48.137,
            "longitude": 11.575,
            "description": "Step-free entrance and roll-in shower.",
        }
        created = await c.post(
            "/api/v1/venues", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        assert created.status_code == 201, created.text
        vid = created.json()["id"]
        fetched = await c.get(
            f"/api/v1/venues/{vid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert fetched.status_code == 200
        detail = fetched.json()
        assert detail["name"] == body["name"]
        assert detail["country_code"] == "DE"
        assert detail["datapoints"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_country_code_filter(client: AsyncClient) -> None:
    await _seed_venue_with_attrs(name="DE one", country="DE", attr_keys={})
    await _seed_venue_with_attrs(name="AT one", country="AT", attr_keys={})
    async with client as c:
        token = await _make_user_token(c, "filter1@example.com", role="reader")
        resp = await c.get(
            "/api/v1/venues",
            params={"country": "DE"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(v["country_code"] == "DE" for v in items)
        assert any(v["name"] == "DE one" for v in items)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_text_q(client: AsyncClient) -> None:
    await _seed_venue_with_attrs(
        name="Hotel Step-free",
        country="DE",
        attr_keys={},
        description="A genuinely step-free hotel near the river.",
    )
    await _seed_venue_with_attrs(
        name="Standard Hotel",
        country="DE",
        attr_keys={},
        description="Two steps at the entrance.",
    )
    async with client as c:
        token = await _make_user_token(c, "fts@example.com", role="reader")
        resp = await c.get(
            "/api/v1/venues",
            params={"q": "step-free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        items = resp.json()["items"]
        names = {v["name"] for v in items}
        assert "Hotel Step-free" in names
        assert "Standard Hotel" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_requires_filter_is_and_across_attributes(client: AsyncClient) -> None:
    # match_both has BOTH attrs; only_one has only step_free; neither has none.
    await _seed_venue_with_attrs(
        name="match_both",
        country="DE",
        attr_keys={"step_free_entrance": True, "roll_in_shower": True},
    )
    await _seed_venue_with_attrs(
        name="only_one", country="DE", attr_keys={"step_free_entrance": True}
    )
    await _seed_venue_with_attrs(name="neither", country="DE", attr_keys={})
    async with client as c:
        token = await _make_user_token(c, "req@example.com", role="reader")
        resp = await c.get(
            "/api/v1/venues",
            params={"requires": "step_free_entrance,roll_in_shower"},
            headers={"Authorization": f"Bearer {token}"},
        )
        names = {v["name"] for v in resp.json()["items"]}
        assert "match_both" in names
        assert "only_one" not in names
        assert "neither" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_requires_excludes_false_values(client: AsyncClient) -> None:
    """A datapoint of value=false should NOT satisfy requires=…"""
    await _seed_venue_with_attrs(
        name="declared_false",
        country="DE",
        attr_keys={"step_free_entrance": False},
    )
    async with client as c:
        token = await _make_user_token(c, "req2@example.com", role="reader")
        resp = await c.get(
            "/api/v1/venues",
            params={"requires": "step_free_entrance"},
            headers={"Authorization": f"Bearer {token}"},
        )
        names = {v["name"] for v in resp.json()["items"]}
        assert "declared_false" not in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cursor_paginates_stably(client: AsyncClient) -> None:
    for i in range(7):
        await _seed_venue_with_attrs(name=f"page_v_{i:02d}", country="ZZ", attr_keys={})
    async with client as c:
        token = await _make_user_token(c, "page@example.com", role="reader")
        first = (
            await c.get(
                "/api/v1/venues",
                params={"country": "ZZ", "limit": 3},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        assert len(first["items"]) == 3
        assert first["next_cursor"] is not None

        second = (
            await c.get(
                "/api/v1/venues",
                params={"country": "ZZ", "limit": 3, "cursor": first["next_cursor"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        third = (
            await c.get(
                "/api/v1/venues",
                params={"country": "ZZ", "limit": 3, "cursor": second["next_cursor"]},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        all_ids = (
            [v["id"] for v in first["items"]]
            + [v["id"] for v in second["items"]]
            + [v["id"] for v in third["items"]]
        )
        # No duplicate items across pages.
        assert len(set(all_ids)) == len(all_ids)
        # Final page (one item) carries no next_cursor.
        assert third["next_cursor"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bad_cursor_is_400(client: AsyncClient) -> None:
    async with client as c:
        token = await _make_user_token(c, "bad@example.com", role="reader")
        resp = await c.get(
            "/api/v1/venues",
            params={"cursor": "not-a-cursor"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_venue_detail_renders_datapoints(client: AsyncClient) -> None:
    vid = await _seed_venue_with_attrs(
        name="rich_profile",
        country="DE",
        attr_keys={
            "step_free_entrance": True,
            "roll_in_shower": True,
        },
    )
    async with client as c:
        token = await _make_user_token(c, "detail@example.com", role="reader")
        resp = await c.get(f"/api/v1/venues/{vid}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        keys = {d["attribute_key"] for d in body["datapoints"]}
        assert keys == {"step_free_entrance", "roll_in_shower"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_venue_404(client: AsyncClient) -> None:
    async with client as c:
        token = await _make_user_token(c, "miss@example.com", role="reader")
        bogus = "01900000-0000-7000-8000-deadbeefcafe"
        resp = await c.get(f"/api/v1/venues/{bogus}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
