"""Integration-scope fixtures.

Integration tests share one Postgres container per session (via the
session-scoped fixtures in ``tests/conftest.py``). Because each test
commits its setup data, rows would otherwise accumulate across tests and
trigger spurious unique-constraint failures (duplicate emails,
idempotency keys, role names, taxonomy versions).

This module's autouse fixture truncates every data table **after** each
integration test, so each test sees a freshly-migrated empty schema.
The migration itself is applied once per session by ``applied_db_url``
in the root conftest.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 -- pytest_asyncio needs runtime visibility on fixture return types
)

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_TABLES_TO_TRUNCATE = (
    # Order matters only if we did not use CASCADE; we do, so a single TRUNCATE
    # over the full set is sufficient. Listed alphabetically for readability.
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
)


@pytest_asyncio.fixture(autouse=True)
async def _truncate_data_tables(applied_db_url: str) -> AsyncIterator[None]:
    """Wipe data + process-local breaker state after each integration test.

    Two kinds of cross-test pollution we kill here:
    * Rows that committed during the test (idempotency keys, emails, etc.)
    * The process-local circuit breaker from ``axis.ingestion.pipeline``,
      which would otherwise carry an OPEN state from a retry-exhaustion
      test into the next test's call path.
    """
    yield
    # 1. Reset the lazy module-level circuit breaker.
    import axis.ingestion.pipeline as _pipeline

    _pipeline._DEFAULT_BREAKER = None

    # 2. Truncate.
    engine = create_async_engine(applied_db_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE " + ", ".join(_TABLES_TO_TRUNCATE) + " RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()
