"""Domain enums.

These are mirrored in Postgres as native ``ENUM`` types so the database
rejects unknown values regardless of the writer's care. The Python ↔ DB
mapping is established in the SQLAlchemy column declarations.
"""

from __future__ import annotations

import enum


class Provenance(enum.StrEnum):
    """Who/what asserted a datapoint. See ARCHITECTURE.md §4.3."""

    HUMAN = "human"
    PARTNER_FEED = "partner_feed"
    AI_EXTRACTION = "ai_extraction"


class ValueType(enum.StrEnum):
    """The Python value-shape a taxonomy attribute accepts."""

    BOOL = "bool"
    NUMERIC = "numeric"
    ENUM = "enum"


class JobStatus(enum.StrEnum):
    """Lifecycle of an :class:`IngestionJob`."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DLQ = "dlq"


class ReviewStatus(enum.StrEnum):
    """Lifecycle of a :class:`ReviewItem`."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


# --- Postgres ENUM names (referenced by both mappers and the alembic migration).
PROVENANCE_ENUM = "provenance"
VALUE_TYPE_ENUM = "value_type"
JOB_STATUS_ENUM = "job_status"
REVIEW_STATUS_ENUM = "review_status"


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Return the ``.value`` strings of an enum, in declaration order.

    SQLAlchemy's :class:`Enum` defaults to sending the *member name* to
    Postgres (``BOOL``), not the value (``bool``). All :class:`SAEnum`
    columns in this project pass ``values_callable=enum_values`` so the
    DB sees the lowercase value that matches the Postgres ``ENUM`` type
    created by the migration.
    """
    return [str(m.value) for m in enum_cls]
