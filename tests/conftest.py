"""Shared test configuration.

A single Postgres container is started per session (when Docker is available)
and the alembic migrations are applied against it. Individual test cases
operate inside an outer transaction that is rolled back, so they observe a
clean state without paying the migration cost per case.

Tests requiring Postgres are tagged with the ``integration`` marker and
automatically skipped when Docker is not reachable.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    # Cheap probe — testcontainers will start the daemon anyway.
    return os.environ.get("AXIS_TEST_DISABLE_DOCKER") != "1"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Spin up a pgvector-enabled Postgres container for the session."""
    if not _docker_available():
        pytest.skip("Docker not available; integration tests require pgvector container")

    # Import inside the fixture so the unit-test path does not need testcontainers.
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg")
    container.start()
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def applied_db_url(postgres_url: str) -> str:
    """Apply alembic migrations once against the container, return the DSN."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    # The settings layer would otherwise override the URL from .env / env vars.
    os.environ["AXIS_DB_DSN"] = postgres_url
    from axis.config import reset_settings_cache

    reset_settings_cache()
    command.upgrade(cfg, "head")
    return postgres_url


@pytest_asyncio.fixture
async def db_session(applied_db_url: str) -> AsyncIterator[AsyncSession]:
    """Yield a fresh session, rolling back at teardown for inter-test isolation."""
    engine = create_async_engine(applied_db_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()
