"""UUID v7 identifier properties — see ADR-0002."""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from axis.ids import new_id


def test_new_id_returns_stdlib_uuid() -> None:
    assert isinstance(new_id(), UUID)


def test_new_id_advertises_version_7() -> None:
    assert new_id().version == 7


def test_new_id_is_unique_across_many_calls() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_new_id_is_time_ordered_within_a_burst() -> None:
    # 100 ids minted in tight succession must be non-decreasing when
    # compared lexicographically, because v7 leads with a 48-bit ms timestamp.
    burst = [new_id() for _ in range(100)]
    sorted_burst = sorted(burst)
    assert burst == sorted_burst


@pytest.mark.parametrize("delay_ms", [5, 20])
def test_new_id_advances_with_wall_clock(delay_ms: int) -> None:
    earlier = new_id()
    time.sleep(delay_ms / 1000)
    later = new_id()
    assert later > earlier
