"""Plain-Python domain types used by the reconciliation rule.

These intentionally do not depend on SQLAlchemy or FastAPI so the
reconciliation logic can be unit-tested with no fixtures, no I/O, and no
ORM round-trips.
"""

from __future__ import annotations

# Dataclass field types are kept at module scope (rather than in a
# TYPE_CHECKING block) for readability; ``from __future__ import annotations``
# means they are strings at runtime regardless.
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID  # noqa: TC003

from axis.db.models.enums import Provenance  # noqa: TC001

# A datapoint's value. Exactly one of these three shapes per row.
AnyValue = bool | Decimal | float | int | str


@dataclass(frozen=True, slots=True)
class ExistingFact:
    """The current *live* datapoint for a (venue, attribute) pair.

    Carries only the fields the reconciliation rule needs — id, provenance,
    and the asserted value. Constructed by the persistence layer from the
    DB row before invoking :func:`axis.domain.reconcile`.
    """

    id: UUID
    provenance: Provenance
    value: AnyValue


@dataclass(frozen=True, slots=True)
class IncomingFact:
    """A candidate datapoint about to be persisted."""

    provenance: Provenance
    value: AnyValue
    confidence: float
