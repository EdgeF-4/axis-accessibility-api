"""Exhaustive truth table for :func:`axis.domain.reconcile`.

The reconciliation rule is the single place that encodes the precedence
policy (ARCHITECTURE.md §4.3). Bugs here cascade silently into incorrect
public values; the table below is therefore intentionally over-covered.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from axis.db.models.enums import Provenance
from axis.domain import (
    ExistingFact,
    IncomingFact,
    InsertLive,
    NoOp,
    StoreSuperseded,
    SupersedeLive,
    precedence_of,
    reconcile,
)

EXISTING_ID = UUID("0190b3ae-0000-7000-8000-000000000001")


def _existing(provenance: Provenance, value: object) -> ExistingFact:
    return ExistingFact(id=EXISTING_ID, provenance=provenance, value=value)  # type: ignore[arg-type]


def _incoming(provenance: Provenance, value: object, confidence: float = 0.9) -> IncomingFact:
    return IncomingFact(provenance=provenance, value=value, confidence=confidence)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Precedence axiom
# ---------------------------------------------------------------------------


def test_precedence_ordering() -> None:
    assert precedence_of(Provenance.HUMAN) > precedence_of(Provenance.PARTNER_FEED)
    assert precedence_of(Provenance.PARTNER_FEED) > precedence_of(Provenance.AI_EXTRACTION)


# ---------------------------------------------------------------------------
# No prior live fact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provenance", list(Provenance))
def test_first_write_is_insert_live(provenance: Provenance) -> None:
    action = reconcile(None, _incoming(provenance, True))
    assert isinstance(action, InsertLive)


# ---------------------------------------------------------------------------
# Incoming dominates existing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("existing_provenance", "incoming_provenance"),
    [
        (Provenance.AI_EXTRACTION, Provenance.PARTNER_FEED),
        (Provenance.AI_EXTRACTION, Provenance.HUMAN),
        (Provenance.PARTNER_FEED, Provenance.HUMAN),
    ],
)
def test_higher_precedence_supersedes(
    existing_provenance: Provenance, incoming_provenance: Provenance
) -> None:
    action = reconcile(
        _existing(existing_provenance, True),
        _incoming(incoming_provenance, False),
    )
    assert isinstance(action, SupersedeLive)
    assert action.existing_id == EXISTING_ID


# ---------------------------------------------------------------------------
# Same precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provenance", list(Provenance))
def test_same_provenance_same_value_is_noop(provenance: Provenance) -> None:
    action = reconcile(
        _existing(provenance, True),
        _incoming(provenance, True),
    )
    assert isinstance(action, NoOp)
    assert action.existing_id == EXISTING_ID


@pytest.mark.parametrize("provenance", list(Provenance))
def test_same_provenance_different_value_supersedes(provenance: Provenance) -> None:
    action = reconcile(
        _existing(provenance, True),
        _incoming(provenance, False),
    )
    assert isinstance(action, SupersedeLive)


# ---------------------------------------------------------------------------
# Incoming is dominated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("existing_provenance", "incoming_provenance"),
    [
        (Provenance.HUMAN, Provenance.PARTNER_FEED),
        (Provenance.HUMAN, Provenance.AI_EXTRACTION),
        (Provenance.PARTNER_FEED, Provenance.AI_EXTRACTION),
    ],
)
def test_lower_precedence_is_stored_superseded(
    existing_provenance: Provenance, incoming_provenance: Provenance
) -> None:
    # Different value -> conflict=True
    action = reconcile(
        _existing(existing_provenance, True),
        _incoming(incoming_provenance, False),
    )
    assert isinstance(action, StoreSuperseded)
    assert action.superseded_by_id == EXISTING_ID
    assert action.conflict is True

    # Same value -> conflict=False (the audit row is still recorded)
    action_same = reconcile(
        _existing(existing_provenance, True),
        _incoming(incoming_provenance, True),
    )
    assert isinstance(action_same, StoreSuperseded)
    assert action_same.conflict is False


# ---------------------------------------------------------------------------
# Numeric / bool / string value equality
# ---------------------------------------------------------------------------


def test_numeric_equality_normalises_across_decimal_float_int() -> None:
    action = reconcile(
        _existing(Provenance.HUMAN, Decimal("90.00")),
        _incoming(Provenance.HUMAN, 90),
    )
    assert isinstance(action, NoOp)


def test_bool_is_not_numerically_equal_to_int_one() -> None:
    # 1 == True in raw Python; reconciliation must NOT treat them as same value
    # for accessibility facts (a numeric attribute and a bool attribute disagreeing
    # would otherwise be silently coalesced).
    action = reconcile(
        _existing(Provenance.HUMAN, True),
        _incoming(Provenance.HUMAN, 1),
    )
    assert isinstance(action, SupersedeLive)


def test_string_equality_is_strict() -> None:
    action_eq = reconcile(
        _existing(Provenance.HUMAN, "left"),
        _incoming(Provenance.HUMAN, "left"),
    )
    assert isinstance(action_eq, NoOp)
    action_neq = reconcile(
        _existing(Provenance.HUMAN, "left"),
        _incoming(Provenance.HUMAN, "right"),
    )
    assert isinstance(action_neq, SupersedeLive)


# ---------------------------------------------------------------------------
# Total function — every input produces exactly one action class
# ---------------------------------------------------------------------------


def test_function_is_total_over_all_provenance_pairs() -> None:
    sentinel = uuid4()
    for ex in [None, *Provenance]:
        existing = (
            None
            if ex is None
            else ExistingFact(
                id=sentinel,
                provenance=ex,
                value=True,
            )
        )
        for inc in Provenance:
            action = reconcile(existing, _incoming(inc, True))
            assert isinstance(action, (InsertLive, SupersedeLive, StoreSuperseded, NoOp))
