"""The persistence step of the pipeline.

Translates :class:`CandidateDatapoint` + :class:`UnknownAttribute` lists
into actual rows: ``datapoints``, ``review_items``, and the reconciliation
chain via ``superseded_by_id``. Reuses
:func:`axis.domain.reconcile` so the precedence policy lives in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from axis.config import get_settings
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
from axis.extraction.schemas import (
    CandidateDatapoint,
    ExtractionResult,
    UnknownAttribute,
)
from axis.ids import new_id

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_AI: Final[Provenance] = Provenance.AI_EXTRACTION


async def _live_existing(
    session: AsyncSession, *, venue_id: UUID, attribute_id: UUID, provenance: Provenance
) -> ExistingFact | None:
    """Return the current live datapoint for the (venue, attribute, provenance) triple."""
    stmt = select(Datapoint).where(
        Datapoint.venue_id == venue_id,
        Datapoint.attribute_id == attribute_id,
        Datapoint.provenance == provenance,
        Datapoint.superseded_by_id.is_(None),
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    value = (
        row.value_bool
        if row.value_bool is not None
        else (float(row.value_numeric) if row.value_numeric is not None else row.value_enum)
    )
    assert value is not None  # noqa: S101 -- value_exactly_one CHECK guarantees this
    return ExistingFact(id=row.id, provenance=row.provenance, value=value)


def _value_columns(
    attribute_value_type: ValueType, value: bool | float | str
) -> dict[str, bool | float | str | None]:
    """Return the value_bool/value_numeric/value_enum dict for ``value``."""
    out: dict[str, bool | float | str | None] = {
        "value_bool": None,
        "value_numeric": None,
        "value_enum": None,
    }
    if attribute_value_type is ValueType.BOOL:
        out["value_bool"] = bool(value)
    elif attribute_value_type is ValueType.NUMERIC:
        out["value_numeric"] = float(value)  # value type narrowed by attribute.value_type
    elif attribute_value_type is ValueType.ENUM:
        out["value_enum"] = str(value)
    return out


async def _attribute_by_key(session: AsyncSession, key: str) -> TaxonomyAttribute | None:
    return (
        await session.execute(select(TaxonomyAttribute).where(TaxonomyAttribute.key == key))
    ).scalar_one_or_none()


async def persist_extraction(
    session: AsyncSession,
    *,
    venue_id: UUID,
    job_id: UUID,
    result: ExtractionResult,
) -> dict[str, int]:
    """Route + reconcile + persist the candidates.

    Returns a small summary counter for metrics: ``persisted``,
    ``reviewed``, ``dropped``, ``conflicts``, ``unknown``.
    """
    s = get_settings()
    persist_t = s.extraction_persist_threshold
    review_t = s.extraction_review_threshold

    summary = {
        "persisted": 0,
        "reviewed": 0,
        "dropped": 0,
        "conflicts": 0,
        "unknown": 0,
    }

    # 1. Unknown attribute candidates → review queue with the flag.
    for unk in result.unknown_attributes:
        await _persist_unknown_review_item(session, venue_id=venue_id, job_id=job_id, unknown=unk)
        summary["unknown"] += 1

    # 2. Known candidates → route by confidence.
    for cand in result.candidates:
        if cand.confidence < review_t:
            summary["dropped"] += 1
            continue
        attr = await _attribute_by_key(session, cand.attribute_key)
        if attr is None:
            # Shouldn't happen — taxonomy filter ran before — but be safe.
            await _persist_unknown_review_item(
                session,
                venue_id=venue_id,
                job_id=job_id,
                unknown=UnknownAttribute(
                    attribute_key=cand.attribute_key,
                    value=cand.value,
                    confidence=cand.confidence,
                    evidence_text=cand.evidence_text,
                ),
            )
            summary["unknown"] += 1
            continue
        if cand.confidence < persist_t:
            await _persist_review_item(
                session,
                venue_id=venue_id,
                job_id=job_id,
                attribute=attr,
                cand=cand,
            )
            summary["reviewed"] += 1
            continue

        # Confidence ≥ persist threshold — reconcile and write.
        existing = await _live_existing(
            session,
            venue_id=venue_id,
            attribute_id=attr.id,
            provenance=_AI,
        )
        action = reconcile(
            existing,
            IncomingFact(provenance=_AI, value=cand.value, confidence=cand.confidence),
        )
        await _apply_action(
            session,
            venue_id=venue_id,
            job_id=job_id,
            attribute=attr,
            cand=cand,
            action=action,
            summary=summary,
        )

    await session.flush()
    return summary


async def _apply_action(
    session: AsyncSession,
    *,
    venue_id: UUID,
    job_id: UUID,
    attribute: TaxonomyAttribute,
    cand: CandidateDatapoint,
    action: object,
    summary: dict[str, int],
) -> None:
    """Materialise a :class:`ReconcileAction` into rows."""
    value_cols = _value_columns(attribute.value_type, cand.value)
    if isinstance(action, NoOp):
        # Nothing to do; matches existing live row exactly.
        return
    if isinstance(action, InsertLive):
        session.add(
            Datapoint(
                id=new_id(),
                venue_id=venue_id,
                attribute_id=attribute.id,
                confidence=cand.confidence,
                provenance=_AI,
                ingestion_job_id=job_id,
                evidence={"text": cand.evidence_text} if cand.evidence_text else None,
                **value_cols,
            )
        )
        summary["persisted"] += 1
        return
    if isinstance(action, SupersedeLive):
        # The partial unique index forbids two live rows for the same
        # (venue, attribute, provenance). We therefore pre-mint the new id,
        # retire the old row first (giving it a non-null superseded_by_id),
        # flush, and only then insert the new live row.
        new_dp_id = new_id()
        old = await session.get(Datapoint, action.existing_id)
        if old is not None:
            old.superseded_by_id = new_dp_id
            await session.flush()
        session.add(
            Datapoint(
                id=new_dp_id,
                venue_id=venue_id,
                attribute_id=attribute.id,
                confidence=cand.confidence,
                provenance=_AI,
                ingestion_job_id=job_id,
                evidence={"text": cand.evidence_text} if cand.evidence_text else None,
                **value_cols,
            )
        )
        summary["persisted"] += 1
        return
    if isinstance(action, StoreSuperseded):
        # Persist the dominated incoming as a pre-superseded audit row.
        session.add(
            Datapoint(
                id=new_id(),
                venue_id=venue_id,
                attribute_id=attribute.id,
                confidence=cand.confidence,
                provenance=_AI,
                ingestion_job_id=job_id,
                superseded_by_id=action.superseded_by_id,
                evidence={"text": cand.evidence_text} if cand.evidence_text else None,
                **value_cols,
            )
        )
        if action.conflict:
            summary["conflicts"] += 1
        summary["persisted"] += 1
        return


async def _persist_review_item(
    session: AsyncSession,
    *,
    venue_id: UUID,
    job_id: UUID,
    attribute: TaxonomyAttribute,
    cand: CandidateDatapoint,
) -> None:
    session.add(
        ReviewItem(
            id=new_id(),
            job_id=job_id,
            venue_id=venue_id,
            attribute_id=attribute.id,
            candidate={
                "attribute_key": cand.attribute_key,
                "value": cand.value,
                "confidence": cand.confidence,
                "evidence_text": cand.evidence_text,
                "unknown_attribute": False,
            },
            status=ReviewStatus.PENDING,
        )
    )


async def _persist_unknown_review_item(
    session: AsyncSession,
    *,
    venue_id: UUID,
    job_id: UUID,
    unknown: UnknownAttribute,
) -> None:
    session.add(
        ReviewItem(
            id=new_id(),
            job_id=job_id,
            venue_id=venue_id,
            attribute_id=None,
            candidate={
                "attribute_key": unknown.attribute_key,
                "value": unknown.value,
                "confidence": unknown.confidence,
                "evidence_text": unknown.evidence_text,
                "unknown_attribute": True,
            },
            status=ReviewStatus.PENDING,
        )
    )
