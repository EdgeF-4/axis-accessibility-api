"""Alembic environment — async, settings-driven.

The DSN is read from :func:`axis.config.get_settings` so the same source of
truth governs the API, the worker, and migrations. ``target_metadata`` is the
project's ``Base.metadata`` after every mapper has been imported.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing axis.db has the side effect of registering every mapper with
# Base.metadata, so autogenerate sees the full schema.
from axis.config import get_settings
from axis.db import models  # noqa: F401  -- mapper registration
from axis.db.base import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# If the caller (test fixture, deploy script) has not set sqlalchemy.url
# programmatically, fall back to the runtime settings DSN. This lets tests
# point alembic at a throwaway container while production reads from env.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().db_dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=None)
    async with connectable.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
