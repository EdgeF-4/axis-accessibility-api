"""Venue mapper.

The :attr:`Venue.search_vector` column is **generated** by Postgres from
``name || venue_type || description`` and indexed with GIN — this is the
FTS path used by ``GET /venues?q=…``. See migration 0001 for the column
definition and the GIN index.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, Computed, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from axis.db.base import Base
from axis.db.models.mixins import TimestampMixin
from axis.ids import new_id

# Generated-column expression — must match the DDL emitted by migration 0001.
_SEARCH_VECTOR_EXPR = (
    "to_tsvector('simple', "
    "coalesce(name, '') || ' ' || "
    "coalesce(venue_type, '') || ' ' || "
    "coalesce(description, ''))"
)


class Venue(Base, TimestampMixin):
    """A physical place whose accessibility is being asserted."""

    __tablename__ = "venues"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_iso2"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    venue_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    description: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)

    # Generated column — populated by Postgres, never written from Python.
    # ``Computed(..., persisted=True)`` tells SA to exclude it from INSERTs.
    # The migration emits identical DDL; this declaration keeps mapper and
    # migration in sync (and lets autogenerate detect drift if either drifts).
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(_SEARCH_VECTOR_EXPR, persisted=True),
    )
