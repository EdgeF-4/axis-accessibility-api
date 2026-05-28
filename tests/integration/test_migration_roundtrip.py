"""Migration round-trip — upgrade → downgrade → upgrade against a live Postgres.

A migration that cannot reverse and re-apply cleanly is a latent rollback
bug. This test catches it before we ship a v1.
"""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import ALEMBIC_INI


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upgrade_then_downgrade_then_upgrade(postgres_url: str) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", postgres_url)

    # alembic env.py drives the migrations through its own asyncio.run(...) loop;
    # call it from a worker thread so it does not collide with pytest-asyncio's.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = create_async_engine(postgres_url, future=True)
    try:
        async with engine.connect() as conn:
            tables = (
                (
                    await conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' ORDER BY table_name"
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    expected = {
        "alembic_version",
        "api_keys",
        "attribute_enum_values",
        "datapoints",
        "dlq_entries",
        "ingestion_jobs",
        "refresh_tokens",
        "review_items",
        "role_assignments",
        "role_scopes",
        "roles",
        "scopes",
        "taxonomy_attributes",
        "taxonomy_categories",
        "taxonomy_versions",
        "users",
        "venues",
    }
    assert expected.issubset(set(tables)), f"missing tables: {expected - set(tables)}"
