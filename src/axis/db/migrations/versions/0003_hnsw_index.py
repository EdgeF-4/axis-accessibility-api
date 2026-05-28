"""HNSW index on datapoints.embedding

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Parameters chosen from pgvector's published guidance for cosine search.
# m = 16 is the default; ef_construction = 64 trades a small build-time
# cost for materially better recall.
_M = 16
_EF_CONSTRUCTION = 64


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_datapoints_embedding_hnsw "
        "ON datapoints USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = {_M}, ef_construction = {_EF_CONSTRUCTION})"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_datapoints_embedding_hnsw")
