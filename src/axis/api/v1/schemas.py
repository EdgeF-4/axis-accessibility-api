"""Pydantic request / response models for the v1 surface.

These are the wire-format types. They do not leak SQLAlchemy mappers
across the HTTP boundary; every field is explicit. Internal IDs are
serialised as canonical UUID strings.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis.db.models.enums import Provenance, ValueType

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class _Out(BaseModel):
    """Base for response schemas — frozen, attribute-friendly."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class TaxonomyAttributeOut(_Out):
    id: UUID
    key: str
    label: str
    description: str | None
    value_type: ValueType
    unit: str | None


class TaxonomyCategoryOut(_Out):
    id: UUID
    key: str
    label: str
    description: str | None
    attributes: list[TaxonomyAttributeOut] = Field(default_factory=list)


class TaxonomyOut(_Out):
    version: str
    label: str | None
    published_at: datetime
    categories: list[TaxonomyCategoryOut]


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------


class VenueCreate(BaseModel):
    """Body for ``POST /venues``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    venue_type: str = Field(min_length=1, max_length=64)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)


class VenueSummary(_Out):
    """List-row shape — small, no datapoints."""

    id: UUID
    name: str
    venue_type: str
    country_code: str
    latitude: float | None
    longitude: float | None
    created_at: datetime


class DatapointOut(_Out):
    attribute_key: str
    category_key: str
    value: bool | float | str | None
    confidence: float
    provenance: Provenance
    verified: bool


class VenueDetail(VenueSummary):
    """Full venue profile with its live datapoints."""

    description: str | None
    source_metadata: dict[str, object]
    datapoints: list[DatapointOut]


class VenueList(BaseModel):
    """Cursor-paginated list response."""

    model_config = ConfigDict(frozen=True)

    items: list[VenueSummary]
    next_cursor: str | None
