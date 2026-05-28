"""Database layer — async SQLAlchemy 2.0.

The public surface is :mod:`axis.db.base` (engine, session factory,
:class:`Base`). Model modules are imported here so that
``Base.metadata`` is populated for Alembic autogenerate.
"""

from __future__ import annotations

from axis.db import models  # noqa: F401  -- side effect: register mappers
from axis.db.base import Base, get_engine, get_session_factory, session_scope

__all__ = ["Base", "get_engine", "get_session_factory", "session_scope"]
