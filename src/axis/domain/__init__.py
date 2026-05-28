"""Framework-free domain types.

This package imports nothing from FastAPI or SQLAlchemy. It is the place
where the *logic* of AXIS lives — primarily the reconciliation rule that
decides what happens when two sources disagree about a fact.
"""

from __future__ import annotations

from axis.domain.reconciliation import (
    InsertLive,
    NoOp,
    ReconcileAction,
    StoreSuperseded,
    SupersedeLive,
    precedence_of,
    reconcile,
)
from axis.domain.types import (
    AnyValue,
    ExistingFact,
    IncomingFact,
)

__all__ = [
    "AnyValue",
    "ExistingFact",
    "IncomingFact",
    "InsertLive",
    "NoOp",
    "ReconcileAction",
    "StoreSuperseded",
    "SupersedeLive",
    "precedence_of",
    "reconcile",
]
