"""Semantic-search helpers.

Given a query vector, find the venues that have at least one live
``ai_extraction`` (or human-verified) datapoint whose embedding is
closest. The query distance is cosine (``<=>``); results are grouped by
venue with the minimum distance retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from axis.db.models import Datapoint, Venue

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class SemanticHit:
    """One row of the semantic-search response."""

    venue_id: UUID
    name: str
    venue_type: str
    country_code: str
    distance: float


async def semantic_search_venues(
    session: AsyncSession,
    *,
    query_vector: list[float],
    limit: int = 20,
) -> list[SemanticHit]:
    """Return up to ``limit`` venues ranked by best matching datapoint.

    ``query_vector`` must be the same dimension as ``datapoints.embedding``
    (384). The HNSW index (migration 0003) provides cosine-similarity
    acceleration; this function uses the ``<=>`` distance operator.
    """
    if not query_vector:
        return []

    # DISTINCT ON (venue_id) keeps the closest matching datapoint per venue.
    sub = (
        select(
            Datapoint.venue_id.label("venue_id"),
            Datapoint.embedding.cosine_distance(query_vector).label("distance"),
        )
        .where(
            Datapoint.embedding.is_not(None),
            Datapoint.superseded_by_id.is_(None),
        )
        .order_by(
            Datapoint.venue_id,
            Datapoint.embedding.cosine_distance(query_vector),
        )
        .distinct(Datapoint.venue_id)
        .subquery()
    )

    stmt = (
        select(
            Venue.id.label("id"),
            Venue.name.label("name"),
            Venue.venue_type.label("venue_type"),
            Venue.country_code.label("country_code"),
            sub.c.distance.label("distance"),
        )
        .join(sub, sub.c.venue_id == Venue.id)
        .order_by(sub.c.distance)
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()
    return [
        SemanticHit(
            venue_id=row.id,
            name=row.name,
            venue_type=row.venue_type,
            country_code=row.country_code,
            distance=float(row.distance),
        )
        for row in rows
    ]
