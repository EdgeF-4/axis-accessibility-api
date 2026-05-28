"""Reconciliation — the pure rule that arbitrates between sources.

When two sources assert (potentially different) values for the same
``(venue, attribute)`` pair, ``reconcile()`` decides what to do. It never
touches the database; the caller translates the returned
:class:`ReconcileAction` into rows.

Precedence (ARCHITECTURE.md §4.3)::

    human > partner_feed > ai_extraction

Outcomes::

    no live fact yet                 -> InsertLive
    incoming dominates the existing  -> SupersedeLive(existing.id)
    same provenance, same value      -> NoOp
    same provenance, different value -> SupersedeLive(existing.id)
    incoming is dominated            -> StoreSuperseded(superseded_by=existing.id, conflict=…)

This is the *only* place in the codebase that encodes the precedence
policy. The truth table is exhaustive — see ``tests/unit/test_reconciliation.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from axis.db.models.enums import Provenance

if TYPE_CHECKING:
    from uuid import UUID

    from axis.domain.types import AnyValue, ExistingFact, IncomingFact

_PRECEDENCE: dict[Provenance, int] = {
    Provenance.AI_EXTRACTION: 1,
    Provenance.PARTNER_FEED: 2,
    Provenance.HUMAN: 3,
}


def precedence_of(p: Provenance) -> int:
    """Return the precedence rank of ``p`` (higher = wins)."""
    return _PRECEDENCE[p]


# ---------------------------------------------------------------------------
# Action ADT
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    """Marker base class for reconciliation outcomes."""


@dataclass(frozen=True, slots=True)
class InsertLive(ReconcileAction):
    """No prior live fact — insert ``incoming`` as the live datapoint."""


@dataclass(frozen=True, slots=True)
class SupersedeLive(ReconcileAction):
    """``incoming`` dominates ``existing``.

    Persist ``incoming`` as the new live row and mark ``existing`` as
    superseded by it (``existing.superseded_by_id = new.id``).
    """

    existing_id: UUID


@dataclass(frozen=True, slots=True)
class StoreSuperseded(ReconcileAction):
    """``incoming`` is dominated by ``existing``.

    Persist ``incoming`` as a pre-superseded audit row pointing at
    ``existing``. ``conflict`` is True iff the dominated fact disagrees in
    value with the live fact — the caller emits a ``reconciliation.conflict``
    metric in that case.
    """

    superseded_by_id: UUID
    conflict: bool


@dataclass(frozen=True, slots=True)
class NoOp(ReconcileAction):
    """``incoming`` matches ``existing`` in both provenance and value — skip."""

    existing_id: UUID


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------


def _values_equal(a: AnyValue, b: AnyValue) -> bool:
    """Compare two datapoint values, normalising numerics across Decimal/float/int.

    Booleans are compared identity-wise (Python treats ``True == 1`` which we
    do not want for accessibility facts).
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, str) or isinstance(b, str):
        return type(a) is type(b) and a == b
    # Numeric path: normalise to Decimal for cross-type equality.
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (TypeError, ValueError, ArithmeticError):
        return False


def reconcile(existing: ExistingFact | None, incoming: IncomingFact) -> ReconcileAction:
    """Decide how to persist ``incoming`` given the current live ``existing``.

    See module docstring for the full truth table. The function is total:
    every (existing, incoming) pair maps to exactly one
    :class:`ReconcileAction` subclass.
    """
    if existing is None:
        return InsertLive()

    ex_rank = _PRECEDENCE[existing.provenance]
    inc_rank = _PRECEDENCE[incoming.provenance]

    if inc_rank > ex_rank:
        return SupersedeLive(existing_id=existing.id)

    if inc_rank == ex_rank:
        if _values_equal(existing.value, incoming.value):
            return NoOp(existing_id=existing.id)
        return SupersedeLive(existing_id=existing.id)

    # inc_rank < ex_rank — existing dominates.
    conflict = not _values_equal(existing.value, incoming.value)
    return StoreSuperseded(superseded_by_id=existing.id, conflict=conflict)
