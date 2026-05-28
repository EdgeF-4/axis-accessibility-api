"""Human-in-the-loop review queue.

Reviewers pull ``ReviewItem`` rows in pending state, inspect the candidate
the model proposed, and resolve each one by *accepting*, *rejecting*, or
*editing*. An accepted candidate is materialised as a human-provenance
:class:`Datapoint` via :func:`axis.domain.reconcile` — so the precedence
policy is the same code path the AI ingestion uses.

Unknown-attribute review items (``candidate.unknown_attribute == true``)
can only be **rejected**: there is no taxonomy attribute to map them to
in v1. Promoting an unknown to a real attribute is a future feature
(taxonomy expansion ADR).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from axis.api.v1.deps import DBSession, Principal, require_scope
from axis.api.v1.pagination import CursorError, decode_cursor, encode_cursor
from axis.db.models import Datapoint, ReviewItem, TaxonomyAttribute
from axis.db.models.enums import Provenance, ReviewStatus, ValueType
from axis.domain import (
    ExistingFact,
    IncomingFact,
    InsertLive,
    NoOp,
    StoreSuperseded,
    SupersedeLive,
    reconcile,
)
from axis.ids import new_id

router = APIRouter(prefix="/review-queue", tags=["review"])
_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReviewItemOut(BaseModel):
    """Wire representation of one pending review item."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    venue_id: UUID
    job_id: UUID
    attribute_id: UUID | None
    candidate: dict[str, object]
    status: ReviewStatus
    created_at: datetime


class ReviewItemList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ReviewItemOut]
    next_cursor: str | None


class ResolveRequest(BaseModel):
    """Body for ``POST /review-queue/{id}/resolve``."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "edit"]
    # Required when action="edit"; ignored otherwise.
    value: bool | float | str | None = None


class ResolveResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: UUID
    status: ReviewStatus
    datapoint_id: UUID | None


# ---------------------------------------------------------------------------
# GET /review-queue
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ReviewItemList,
    dependencies=[Depends(require_scope("review:resolve"))],
)
async def list_review_queue(
    session: DBSession,
    review_status: Annotated[
        ReviewStatus | None, Query(alias="status", description="filter by status")
    ] = None,
    venue_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ReviewItemList:
    """Paginated list of review items. Defaults to ``status=pending``."""
    effective_status = review_status or ReviewStatus.PENDING
    stmt = select(ReviewItem).where(ReviewItem.status == effective_status)
    if venue_id is not None:
        stmt = stmt.where(ReviewItem.venue_id == venue_id)

    if cursor is not None:
        try:
            parts = decode_cursor(cursor)
        except CursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"bad cursor: {exc}"
            ) from exc
        if len(parts) != 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad cursor shape")
        try:
            cur_created = datetime.fromisoformat(parts[0])
            cur_id = UUID(parts[1])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="bad cursor content"
            ) from exc
        stmt = stmt.where(
            (ReviewItem.created_at < cur_created)
            | ((ReviewItem.created_at == cur_created) & (ReviewItem.id < cur_id))
        )

    stmt = stmt.order_by(ReviewItem.created_at.desc(), ReviewItem.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor((last.created_at.isoformat(), str(last.id)))

    return ReviewItemList(
        items=[ReviewItemOut.model_validate(r, from_attributes=True) for r in rows],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# POST /review-queue/{id}/resolve
# ---------------------------------------------------------------------------


@router.post(
    "/{review_id}/resolve",
    response_model=ResolveResult,
    dependencies=[Depends(require_scope("review:resolve"))],
)
async def resolve_review_item(
    review_id: UUID,
    body: ResolveRequest,
    session: DBSession,
    principal: Principal,
) -> ResolveResult:
    """Accept / reject / edit a pending review item."""
    item = await session.get(ReviewItem, review_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review item not found")
    if item.status is not ReviewStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"already resolved as {item.status.value}",
        )

    is_unknown = bool(item.candidate.get("unknown_attribute"))

    if body.action == "reject":
        item.status = ReviewStatus.REJECTED
        item.resolved_by = principal.subject_id
        item.resolved_at = datetime.now(UTC)
        item.resolution = {"action": "reject"}
        return ResolveResult(review_id=item.id, status=item.status, datapoint_id=None)

    # accept / edit require a real taxonomy attribute.
    if is_unknown or item.attribute_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "unknown-attribute candidates can only be rejected in v1; "
                "promote the attribute via /taxonomy/versions first"
            ),
        )

    attribute = await session.get(TaxonomyAttribute, item.attribute_id)
    if attribute is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="referenced attribute is missing",
        )

    if body.action == "accept":
        chosen_value: bool | float | str | None = item.candidate.get("value")  # type: ignore[assignment]
        if chosen_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="candidate has no value to accept",
            )
    else:  # action == "edit"
        if body.value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="action=edit requires a 'value' field",
            )
        chosen_value = body.value

    datapoint_id = await _materialise_human_datapoint(
        session,
        venue_id=item.venue_id,
        attribute=attribute,
        value=chosen_value,
        reviewer_id=principal.subject_id,
    )

    item.status = ReviewStatus.ACCEPTED if body.action == "accept" else ReviewStatus.EDITED
    item.resolved_by = principal.subject_id
    item.resolved_at = datetime.now(UTC)
    item.resolution = {"action": body.action, "value": chosen_value}

    return ResolveResult(review_id=item.id, status=item.status, datapoint_id=datapoint_id)


# ---------------------------------------------------------------------------
# Internals — write a human datapoint through the precedence rule
# ---------------------------------------------------------------------------


async def _materialise_human_datapoint(
    session: DBSession,
    *,
    venue_id: UUID,
    attribute: TaxonomyAttribute,
    value: bool | float | str,
    reviewer_id: UUID,
) -> UUID | None:
    """Write a HUMAN-provenance Datapoint using :func:`reconcile`."""
    # Existing live HUMAN row (if any).
    existing_row = (
        await session.execute(
            select(Datapoint).where(
                Datapoint.venue_id == venue_id,
                Datapoint.attribute_id == attribute.id,
                Datapoint.provenance == Provenance.HUMAN,
                Datapoint.superseded_by_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    existing: ExistingFact | None = None
    if existing_row is not None:
        ex_value = (
            existing_row.value_bool
            if existing_row.value_bool is not None
            else float(existing_row.value_numeric)
            if existing_row.value_numeric is not None
            else existing_row.value_enum
        )
        assert ex_value is not None  # noqa: S101 -- value_exactly_one CHECK
        existing = ExistingFact(id=existing_row.id, provenance=Provenance.HUMAN, value=ex_value)

    incoming = IncomingFact(provenance=Provenance.HUMAN, value=value, confidence=1.0)
    action = reconcile(existing, incoming)

    value_cols: dict[str, bool | float | str | None] = {
        "value_bool": None,
        "value_numeric": None,
        "value_enum": None,
    }
    if attribute.value_type is ValueType.BOOL:
        value_cols["value_bool"] = bool(value)
    elif attribute.value_type is ValueType.NUMERIC:
        value_cols["value_numeric"] = float(value)
    elif attribute.value_type is ValueType.ENUM:
        value_cols["value_enum"] = str(value)

    if isinstance(action, NoOp):
        _logger.info("review.resolve.noop", venue_id=str(venue_id), attribute=attribute.key)
        return action.existing_id

    if isinstance(action, InsertLive):
        new_dp = Datapoint(
            id=new_id(),
            venue_id=venue_id,
            attribute_id=attribute.id,
            confidence=1.0,
            provenance=Provenance.HUMAN,
            verified_by=reviewer_id,
            **value_cols,
        )
        session.add(new_dp)
        await session.flush()
        return new_dp.id

    if isinstance(action, SupersedeLive):
        new_dp_id = new_id()
        if existing_row is not None:
            existing_row.superseded_by_id = new_dp_id
            await session.flush()
        session.add(
            Datapoint(
                id=new_dp_id,
                venue_id=venue_id,
                attribute_id=attribute.id,
                confidence=1.0,
                provenance=Provenance.HUMAN,
                verified_by=reviewer_id,
                **value_cols,
            )
        )
        await session.flush()
        return new_dp_id

    if isinstance(action, StoreSuperseded):
        # A human reviewer cannot be dominated by anything (HUMAN is top of
        # the precedence ladder). This branch is unreachable for HUMAN incoming
        # but we handle it defensively rather than asserting.
        _logger.warning(
            "review.resolve.unexpected_store_superseded",
            venue_id=str(venue_id),
            attribute=attribute.key,
        )
        return None

    return None
