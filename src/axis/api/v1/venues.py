"""Venues — list, detail, create."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from axis.api.v1.deps import DBSession, require_scope
from axis.api.v1.pagination import CursorError, decode_cursor, encode_cursor
from axis.api.v1.schemas import (
    DatapointOut,
    VenueCreate,
    VenueDetail,
    VenueList,
    VenueSummary,
)
from axis.db.models import Venue
from axis.db.queries.venues import VenueListFilter, list_live_datapoints, list_venues
from axis.ids import new_id

router = APIRouter(prefix="/venues", tags=["venues"])


def _resolve_cursor(raw: str | None) -> tuple[datetime, UUID] | None:
    if raw is None:
        return None
    try:
        parts = decode_cursor(raw)
    except CursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"bad cursor: {exc}"
        ) from exc
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad cursor shape")
    try:
        return datetime.fromisoformat(parts[0]), UUID(parts[1])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="bad cursor content"
        ) from exc


@router.get(
    "",
    response_model=VenueList,
    dependencies=[Depends(require_scope("venue:read"))],
)
async def list_venues_endpoint(
    session: DBSession,
    q: Annotated[str | None, Query(description="Full-text search over venue text")] = None,
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    near: Annotated[str | None, Query(description="lat,lng — e.g. 48.137,11.575")] = None,
    radius_km: Annotated[float | None, Query(gt=0, le=500)] = None,
    requires: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated taxonomy attribute keys; matched venues have "
                "a live datapoint with value=true for EVERY listed key."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> VenueList:
    """List venues with full-text + bounding-box + attribute-requires filters."""
    near_pair: tuple[float, float] | None = None
    if near is not None:
        try:
            lat_str, lon_str = near.split(",", maxsplit=1)
            near_pair = (float(lat_str), float(lon_str))
        except (ValueError, IndexError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="near must look like 'lat,lng'",
            ) from exc
        if radius_km is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="radius_km is required when near is supplied",
            )

    requires_tuple: tuple[str, ...] = ()
    if requires:
        requires_tuple = tuple(k.strip() for k in requires.split(",") if k.strip())

    filter_ = VenueListFilter(
        q=q,
        country=country,
        near=near_pair,
        radius_km=radius_km,
        requires=requires_tuple,
        limit=limit,
        cursor=_resolve_cursor(cursor),
    )
    rows, has_more = await list_venues(session, filter_)

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor((last.created_at.isoformat(), str(last.id)))

    items = [VenueSummary.model_validate(row, from_attributes=True) for row in rows]
    return VenueList(items=items, next_cursor=next_cursor)


@router.get(
    "/{venue_id}",
    response_model=VenueDetail,
    dependencies=[Depends(require_scope("venue:read"))],
)
async def get_venue(venue_id: UUID, session: DBSession) -> VenueDetail:
    """Return the full accessibility profile for ``venue_id``."""
    venue = await session.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="venue not found")
    rows = await list_live_datapoints(session, venue_id)
    datapoints = [
        DatapointOut(
            attribute_key=r.attribute_key,
            category_key=r.category_key,
            value=(
                r.value_bool
                if r.value_bool is not None
                else r.value_numeric
                if r.value_numeric is not None
                else r.value_enum
            ),
            confidence=r.confidence,
            provenance=r.provenance,
            verified=r.verified,
        )
        for r in rows
    ]
    return VenueDetail(
        id=venue.id,
        name=venue.name,
        venue_type=venue.venue_type,
        country_code=venue.country_code,
        latitude=float(venue.latitude) if venue.latitude is not None else None,
        longitude=float(venue.longitude) if venue.longitude is not None else None,
        created_at=venue.created_at,
        description=venue.description,
        source_metadata=venue.source_metadata,
        datapoints=datapoints,
    )


@router.post(
    "",
    response_model=VenueSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("venue:write"))],
)
async def create_venue(body: VenueCreate, session: DBSession) -> VenueSummary:
    """Insert a new venue. Idempotency is the caller's responsibility for now."""
    venue = Venue(
        id=new_id(),
        name=body.name,
        venue_type=body.venue_type,
        country_code=body.country_code,
        latitude=body.latitude,
        longitude=body.longitude,
        description=body.description,
        source_metadata=body.source_metadata,
    )
    session.add(venue)
    await session.flush()
    await session.refresh(venue, attribute_names=["created_at"])
    return VenueSummary.model_validate(venue, from_attributes=True)
