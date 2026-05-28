"""Venue list + detail queries.

The list query supports four orthogonal filters — full-text ``q``,
bounding-box ``near/radius_km``, ``country``, and ``requires=…`` — and
cursor pagination. The ``requires`` filter is the load-bearing one:
"venues with a live datapoint of value=true for every attribute in this
set." It is expressed as a single subquery joining datapoints to
taxonomy_attributes, with a HAVING count check — no N+1.

The cursor is opaque + signed (:mod:`axis.api.v1.pagination`); we sort
by ``(created_at DESC, id DESC)`` so v7-id time-ordering survives the
sort even when two venues share a millisecond.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select

from axis.db.models import Datapoint, TaxonomyAttribute, Venue

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select

    from axis.db.models.enums import Provenance


@dataclass(frozen=True, slots=True)
class VenueListFilter:
    """Server-side validated filter set for ``GET /venues``."""

    q: str | None = None
    country: str | None = None
    near: tuple[float, float] | None = None
    radius_km: float | None = None
    requires: tuple[str, ...] = ()
    limit: int = 50
    cursor: tuple[datetime, UUID] | None = None  # (created_at, id) cursor


def _build_base_stmt(f: VenueListFilter) -> Select[tuple[Venue]]:
    stmt = select(Venue)

    if f.q:
        stmt = stmt.where(Venue.search_vector.op("@@")(func.plainto_tsquery("simple", f.q)))

    if f.country:
        stmt = stmt.where(Venue.country_code == f.country)

    if f.near is not None and f.radius_km is not None:
        lat, lon = f.near
        # Crude bounding box — sufficient for v1 (no PostGIS, ARCHITECTURE.md §11).
        # 1 degree of latitude ≈ 111 km; longitude scales by cos(lat).
        d_lat = f.radius_km / 111.0
        cos_lat = max(0.000_001, math.cos(math.radians(lat)))  # avoid div/0 at poles
        d_lon = f.radius_km / (111.0 * cos_lat)
        stmt = stmt.where(
            Venue.latitude.between(lat - d_lat, lat + d_lat),
            Venue.longitude.between(lon - d_lon, lon + d_lon),
        )

    if f.requires:
        # Sub-select: venues with a live `value_bool = true` datapoint for
        # every attribute key in `requires`. Single JOIN with HAVING.
        sub = (
            select(Datapoint.venue_id)
            .join(TaxonomyAttribute, TaxonomyAttribute.id == Datapoint.attribute_id)
            .where(
                TaxonomyAttribute.key.in_(f.requires),
                Datapoint.value_bool.is_(True),
                Datapoint.superseded_by_id.is_(None),
            )
            .group_by(Datapoint.venue_id)
            .having(func.count(func.distinct(TaxonomyAttribute.id)) == len(set(f.requires)))
        )
        stmt = stmt.where(Venue.id.in_(sub))

    if f.cursor is not None:
        cur_created, cur_id = f.cursor
        # Strict ``(created_at, id) < cursor`` lexicographic comparison.
        stmt = stmt.where(
            and_(
                Venue.created_at <= cur_created,
                ~and_(Venue.created_at == cur_created, Venue.id >= cur_id),
            )
        )

    return stmt.order_by(Venue.created_at.desc(), Venue.id.desc()).limit(f.limit + 1)


async def list_venues(session: AsyncSession, f: VenueListFilter) -> tuple[Sequence[Venue], bool]:
    """Return the page rows plus a ``has_more`` flag derived from the +1 probe."""
    stmt = _build_base_stmt(f)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > f.limit
    if has_more:
        rows = rows[: f.limit]
    return rows, has_more


@dataclass(frozen=True, slots=True)
class LiveDatapointRow:
    """A row shape for the detail endpoint — pre-joined with taxonomy keys."""

    attribute_key: str
    category_key: str
    value_bool: bool | None
    value_numeric: float | None
    value_enum: str | None
    confidence: float
    provenance: Provenance
    verified: bool


async def list_live_datapoints(session: AsyncSession, venue_id: UUID) -> list[LiveDatapointRow]:
    """Return the *live* datapoints for ``venue_id`` joined with their attribute key.

    "Live" = ``superseded_by_id IS NULL``. The result is precedence-already-
    chosen because the live row is the one the precedence rule kept current.
    """
    from axis.db.models.taxonomy import TaxonomyCategory

    stmt = (
        select(
            TaxonomyAttribute.key.label("attribute_key"),
            TaxonomyCategory.key.label("category_key"),
            Datapoint.value_bool,
            Datapoint.value_numeric,
            Datapoint.value_enum,
            Datapoint.confidence,
            Datapoint.provenance,
            Datapoint.verified_by.isnot(None).label("verified"),
        )
        .join(TaxonomyAttribute, TaxonomyAttribute.id == Datapoint.attribute_id)
        .join(TaxonomyCategory, TaxonomyCategory.id == TaxonomyAttribute.category_id)
        .where(
            Datapoint.venue_id == venue_id,
            Datapoint.superseded_by_id.is_(None),
        )
        .order_by(TaxonomyCategory.key, TaxonomyAttribute.key)
    )
    return [
        LiveDatapointRow(
            attribute_key=row.attribute_key,
            category_key=row.category_key,
            value_bool=row.value_bool,
            value_numeric=float(row.value_numeric) if row.value_numeric is not None else None,
            value_enum=row.value_enum,
            confidence=float(row.confidence),
            provenance=row.provenance,
            verified=bool(row.verified),
        )
        for row in (await session.execute(stmt)).all()
    ]
