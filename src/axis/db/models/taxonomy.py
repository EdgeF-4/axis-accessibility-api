"""Taxonomy mappers — the controlled vocabulary as data.

Per ARCHITECTURE.md §2.3, taxonomy is *not* an enum-in-code. Categories,
attributes, units, and allowed value-types are tables. Each row is versioned
via the parent :class:`TaxonomyVersion`; adding an attribute is a migration
+ seed edit, not a code deploy.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axis.db.base import Base
from axis.db.models.enums import VALUE_TYPE_ENUM, ValueType, enum_values
from axis.db.models.mixins import TimestampMixin
from axis.ids import new_id


class TaxonomyVersion(Base):
    """A snapshot of the taxonomy. New versions are additive; superseded
    versions remain queryable for historical audits."""

    __tablename__ = "taxonomy_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    semver: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TaxonomyCategory(Base, TimestampMixin):
    """A top-level grouping (mobility, vision, hearing, cognitive, sensory)."""

    __tablename__ = "taxonomy_categories"
    __table_args__ = (UniqueConstraint("key", "version_id", name="uq_category_key_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("taxonomy_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class TaxonomyAttribute(Base, TimestampMixin):
    """A single addressable accessibility attribute (e.g. ``roll_in_shower``).

    The ``value_type`` controls which value column in :class:`Datapoint` is
    populated; the application enforces that pairing at insert.
    """

    __tablename__ = "taxonomy_attributes"
    __table_args__ = (UniqueConstraint("key", "version_id", name="uq_attribute_key_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    category_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("taxonomy_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("taxonomy_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[ValueType] = mapped_column(
        SAEnum(
            ValueType,
            name=VALUE_TYPE_ENUM,
            native_enum=True,
            create_type=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    unit: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)


class AttributeEnumValue(Base):
    """The allowed values for an attribute whose value_type is ``enum``."""

    __tablename__ = "attribute_enum_values"
    __table_args__ = (UniqueConstraint("attribute_id", "value", name="uq_attribute_enum_value"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    attribute_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("taxonomy_attributes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
