"""Read-side query helpers.

Each module here exposes one or more pure functions that take an open
``AsyncSession`` and return typed rows / domain objects. Keeping the
SELECT shapes outside the API layer means the same query can be reused
from a worker, a CLI, or a future GraphQL adapter without dragging
FastAPI types along.
"""

from __future__ import annotations
