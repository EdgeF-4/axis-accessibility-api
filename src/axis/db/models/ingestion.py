"""Ingestion-pipeline mappers — jobs, review items, dead-letter entries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axis.db.base import Base
from axis.db.models.enums import (
    JOB_STATUS_ENUM,
    REVIEW_STATUS_ENUM,
    JobStatus,
    ReviewStatus,
    enum_values,
)
from axis.db.models.mixins import TimestampMixin
from axis.ids import new_id


class IngestionJob(Base, TimestampMixin):
    """One unit of AI-ingestion work.

    The ``idempotency_key`` is UNIQUE; re-POSTing the same key returns the
    existing job rather than enqueueing twice (ARCHITECTURE.md §4.2).
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ingestion_jobs_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    venue_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(
            JobStatus,
            name=JOB_STATUS_ENUM,
            native_enum=True,
            create_type=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=JobStatus.QUEUED,
    )
    input: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewItem(Base, TimestampMixin):
    """A low-confidence extraction routed to a human reviewer."""

    __tablename__ = "review_items"
    __table_args__ = (Index("ix_review_items_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attribute_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("taxonomy_attributes.id", ondelete="RESTRICT"), index=True
    )
    candidate: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(
            ReviewStatus,
            name=REVIEW_STATUS_ENUM,
            native_enum=True,
            create_type=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    resolved_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class DLQEntry(Base, TimestampMixin):
    """A terminal failure with its full payload preserved for replay."""

    __tablename__ = "dlq_entries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    terminal_error: Mapped[str] = mapped_column(Text, nullable=False)
