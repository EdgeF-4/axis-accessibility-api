"""Datapoint mapper — the structured accessibility fact.

Constraints (enforced in the DB, not in app code):

* ``confidence`` ∈ [0, 1]                                                   (CHECK)
* exactly one of ``value_bool`` / ``value_numeric`` / ``value_enum`` is set (CHECK)
* at most one *live* datapoint per ``(venue, attribute, provenance)``
  where ``superseded_by_id IS NULL``                                        (partial UNIQUE)

The pairing between ``value_*`` and the parent attribute's ``value_type`` is
enforced at the application boundary (Pydantic + reconciliation), not as a
CHECK — Postgres CHECK cannot reach into another table.
"""

from __future__ import annotations

from uuid import UUID

# pgvector exposes a SA type adapter for the ``vector`` Postgres type.
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axis.db.base import Base
from axis.db.models.enums import PROVENANCE_ENUM, Provenance, enum_values
from axis.db.models.mixins import TimestampMixin
from axis.ids import new_id

EMBEDDING_DIMENSIONS: int = 384  # all-MiniLM-L6-v2; locked in upcoming ADR-0004.


class Datapoint(Base, TimestampMixin):
    """A single, provenanced accessibility fact about a venue."""

    __tablename__ = "datapoints"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint(
            "(CASE WHEN value_bool IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN value_enum IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="value_exactly_one",
        ),
        # The "live datapoint" partial unique — declared here so it lives next
        # to the table definition; the migration emits the same DDL.
        Index(
            "uq_datapoints_live_fact",
            "venue_id",
            "attribute_id",
            "provenance",
            unique=True,
            postgresql_where="superseded_by_id IS NULL",
        ),
        Index("ix_datapoints_venue_id", "venue_id"),
        Index("ix_datapoints_attribute_id", "attribute_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    venue_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("taxonomy_attributes.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Exactly one of these is non-null (enforced by ``value_exactly_one``).
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_numeric: Mapped[float | None] = mapped_column(Numeric(18, 6))
    value_enum: Mapped[str | None] = mapped_column(String(128))

    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    provenance: Mapped[Provenance] = mapped_column(
        SAEnum(
            Provenance,
            name=PROVENANCE_ENUM,
            native_enum=True,
            create_type=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )

    verified_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    ingestion_job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("ingestion_jobs.id", ondelete="SET NULL")
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("datapoints.id", ondelete="SET NULL")
    )

    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
