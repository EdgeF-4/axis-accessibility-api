"""defer datapoints.superseded_by_id FK to commit time

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT = "fk_datapoints_superseded_by_id_datapoints"


def upgrade() -> None:
    # The SupersedeLive reconciliation path needs to (1) update the old
    # live row to point at the about-to-be-inserted new row, then (2) insert
    # the new row. With an IMMEDIATE FK, step (1) fails because the target
    # row does not yet exist. Deferring to commit lets both writes happen
    # inside a single transaction without losing the integrity guarantee:
    # commit still fails the txn if the FK ends up dangling.
    op.execute(
        f"ALTER TABLE datapoints ALTER CONSTRAINT {_CONSTRAINT} DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE datapoints ALTER CONSTRAINT {_CONSTRAINT} NOT DEFERRABLE")
