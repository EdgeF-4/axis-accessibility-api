"""UUID v7 identifier helper. See ADR-0002 for the rationale.

The one rule: every primary key in AXIS is minted by :func:`new_id`. Server-
side defaults (`gen_random_uuid()`) are deliberately not used so that the
contract is uniform across writers (API handler, worker, seed loader, tests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from uuid_utils.compat import uuid7 as _uuid7

if TYPE_CHECKING:
    from uuid import UUID


def new_id() -> UUID:
    """Return a fresh UUID v7 (RFC 9562 §5.7).

    Time-ordered: the leading 48 bits encode a millisecond Unix timestamp,
    so ``ORDER BY id`` is a usable creation-order proxy across the table.
    """
    return _uuid7()
