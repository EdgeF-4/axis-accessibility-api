"""initial schema — IAM, taxonomy, venues, datapoints, ingestion

Revision ID: 0001
Revises:
Create Date: 2026-05-28
"""
# Migrations are DDL-as-Python; SQLAlchemy's postgresql dialect stubs are
# intentionally loose on column-type constructors. Forcing strict typing here
# costs more than it earns.
# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Postgres-side helpers
# ---------------------------------------------------------------------------

PROVENANCE_VALUES = ("human", "partner_feed", "ai_extraction")
VALUE_TYPE_VALUES = ("bool", "numeric", "enum")
JOB_STATUS_VALUES = ("queued", "running", "succeeded", "failed", "dlq")
REVIEW_STATUS_VALUES = ("pending", "accepted", "rejected", "edited")


def _create_enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    enum = postgresql.ENUM(*values, name=name, create_type=False)
    enum.create(op.get_bind(), checkfirst=True)
    return enum


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # --- extensions ---------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- enums --------------------------------------------------------------
    provenance = _create_enum("provenance", PROVENANCE_VALUES)
    value_type = _create_enum("value_type", VALUE_TYPE_VALUES)
    job_status = _create_enum("job_status", JOB_STATUS_VALUES)
    review_status = _create_enum("review_status", REVIEW_STATUS_VALUES)

    # --- IAM ----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(255), nullable=False),
    )

    op.create_table(
        "scopes",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(255), nullable=False),
    )

    op.create_table(
        "role_assignments",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "role_scopes",
        sa.Column(
            "role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "scope_name",
            sa.String(64),
            sa.ForeignKey("scopes.name", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_org", sa.String(255)),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    # --- taxonomy -----------------------------------------------------------
    op.create_table(
        "taxonomy_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("semver", sa.String(32), nullable=False, unique=True),
        sa.Column("label", sa.String(255)),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "taxonomy_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key", "version_id", name="uq_category_key_version"),
    )
    op.create_index("ix_taxonomy_categories_version_id", "taxonomy_categories", ["version_id"])

    op.create_table(
        "taxonomy_attributes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("value_type", value_type, nullable=False),
        sa.Column("unit", sa.String(32)),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key", "version_id", name="uq_attribute_key_version"),
        sa.CheckConstraint(
            "(value_type = 'numeric') OR (unit IS NULL)",
            name="ck_taxonomy_attributes_unit_requires_numeric",
        ),
    )
    op.create_index("ix_taxonomy_attributes_category_id", "taxonomy_attributes", ["category_id"])
    op.create_index("ix_taxonomy_attributes_version_id", "taxonomy_attributes", ["version_id"])

    op.create_table(
        "attribute_enum_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "attribute_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_attributes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.UniqueConstraint("attribute_id", "value", name="uq_attribute_enum_value"),
    )
    op.create_index(
        "ix_attribute_enum_values_attribute_id",
        "attribute_enum_values",
        ["attribute_id"],
    )

    # --- venues -------------------------------------------------------------
    op.create_table(
        "venues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("venue_type", sa.String(64), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("description", sa.Text()),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_venues_latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_venues_longitude_range"),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_venues_country_code_iso2"),
    )
    op.create_index("ix_venues_name", "venues", ["name"])
    op.create_index("ix_venues_venue_type", "venues", ["venue_type"])
    op.create_index("ix_venues_country_code", "venues", ["country_code"])

    # Generated tsvector column + GIN index for FTS.
    op.execute(
        """
        ALTER TABLE venues
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'simple',
                coalesce(name, '') || ' ' ||
                coalesce(venue_type, '') || ' ' ||
                coalesce(description, '')
            )
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_venues_search_vector ON venues USING GIN (search_vector)")

    # --- ingestion jobs -----------------------------------------------------
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Uuid(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("status", job_status, nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ingestion_jobs_venue_id", "ingestion_jobs", ["venue_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    # --- datapoints (depend on venues, attributes, users, ingestion_jobs) ---
    op.create_table(
        "datapoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Uuid(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attribute_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_attributes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value_bool", sa.Boolean()),
        sa.Column("value_numeric", sa.Numeric(18, 6)),
        sa.Column("value_enum", sa.String(128)),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("provenance", provenance, nullable=False),
        sa.Column(
            "verified_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "ingestion_job_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("superseded_by_id", sa.Uuid()),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("embedding", Vector(384)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_datapoints_confidence_range"),
        sa.CheckConstraint(
            "(CASE WHEN value_bool IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN value_enum IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_datapoints_value_exactly_one",
        ),
    )
    # Self-FK added after table create so the column exists.
    op.create_foreign_key(
        "fk_datapoints_superseded_by_id_datapoints",
        "datapoints",
        "datapoints",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_datapoints_venue_id", "datapoints", ["venue_id"])
    op.create_index("ix_datapoints_attribute_id", "datapoints", ["attribute_id"])
    # Partial unique — the "one live fact per (venue, attribute, provenance)" invariant.
    op.create_index(
        "uq_datapoints_live_fact",
        "datapoints",
        ["venue_id", "attribute_id", "provenance"],
        unique=True,
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )

    # --- review queue + DLQ -------------------------------------------------
    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "venue_id",
            sa.Uuid(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attribute_id",
            sa.Uuid(),
            sa.ForeignKey("taxonomy_attributes.id", ondelete="RESTRICT"),
        ),
        sa.Column("candidate", postgresql.JSONB(), nullable=False),
        sa.Column("status", review_status, nullable=False),
        sa.Column(
            "resolved_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_review_items_job_id", "review_items", ["job_id"])
    op.create_index("ix_review_items_venue_id", "review_items", ["venue_id"])
    op.create_index("ix_review_items_attribute_id", "review_items", ["attribute_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])

    op.create_table(
        "dlq_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("terminal_error", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("dlq_entries")
    op.drop_table("review_items")
    op.drop_index("uq_datapoints_live_fact", table_name="datapoints")
    op.drop_index("ix_datapoints_attribute_id", table_name="datapoints")
    op.drop_index("ix_datapoints_venue_id", table_name="datapoints")
    op.drop_constraint(
        "fk_datapoints_superseded_by_id_datapoints", "datapoints", type_="foreignkey"
    )
    op.drop_table("datapoints")
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_venue_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.execute("DROP INDEX IF EXISTS ix_venues_search_vector")
    op.execute("ALTER TABLE venues DROP COLUMN IF EXISTS search_vector")
    op.drop_index("ix_venues_country_code", table_name="venues")
    op.drop_index("ix_venues_venue_type", table_name="venues")
    op.drop_index("ix_venues_name", table_name="venues")
    op.drop_table("venues")
    op.drop_index("ix_attribute_enum_values_attribute_id", table_name="attribute_enum_values")
    op.drop_table("attribute_enum_values")
    op.drop_index("ix_taxonomy_attributes_version_id", table_name="taxonomy_attributes")
    op.drop_index("ix_taxonomy_attributes_category_id", table_name="taxonomy_attributes")
    op.drop_table("taxonomy_attributes")
    op.drop_index("ix_taxonomy_categories_version_id", table_name="taxonomy_categories")
    op.drop_table("taxonomy_categories")
    op.drop_table("taxonomy_versions")
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("role_scopes")
    op.drop_table("role_assignments")
    op.drop_table("scopes")
    op.drop_table("roles")
    op.drop_table("users")

    for enum_name in ("review_status", "job_status", "value_type", "provenance"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    # Extensions deliberately not dropped — they may be in use elsewhere.
