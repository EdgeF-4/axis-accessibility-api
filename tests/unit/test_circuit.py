"""Circuit-breaker state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from axis.ingestion.circuit import CircuitBreaker, CircuitOpenError

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def now_seq() -> Iterator[list[float]]:
    """Patch axis.ingestion.circuit._NOW to a controllable iterator."""
    times: list[float] = []

    def fake_now() -> float:
        return times[-1] if times else 0.0

    with patch("axis.ingestion.circuit._NOW", fake_now):
        yield times


def advance(times: list[float], to: float) -> None:
    times.append(to)


def test_closed_allows_calls(now_seq: list[float]) -> None:
    advance(now_seq, 0.0)
    cb = CircuitBreaker(fails_to_open=3, window_seconds=10, open_seconds=5)
    cb.before_call()  # must not raise
    assert cb.state == "closed"


def test_opens_after_threshold_failures(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=3, window_seconds=10, open_seconds=5)
    for t in (0.0, 0.5, 1.0):
        advance(now_seq, t)
        cb.on_failure()
    assert cb.state == "open"


def test_open_rejects_calls(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=2, window_seconds=10, open_seconds=5)
    advance(now_seq, 0.0)
    cb.on_failure()
    advance(now_seq, 0.1)
    cb.on_failure()
    advance(now_seq, 0.2)
    with pytest.raises(CircuitOpenError):
        cb.before_call()


def test_half_open_after_cool_down(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=1, window_seconds=10, open_seconds=5)
    advance(now_seq, 0.0)
    cb.on_failure()
    assert cb.state == "open"
    advance(now_seq, 6.0)  # past open_seconds
    cb.before_call()  # transitions to half_open + probe in flight
    assert cb.state == "half_open"


def test_half_open_success_closes(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=1, window_seconds=10, open_seconds=1)
    advance(now_seq, 0.0)
    cb.on_failure()
    advance(now_seq, 2.0)
    cb.before_call()
    cb.on_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=1, window_seconds=10, open_seconds=1)
    advance(now_seq, 0.0)
    cb.on_failure()
    advance(now_seq, 2.0)
    cb.before_call()
    cb.on_failure()
    assert cb.state == "open"


def test_half_open_concurrent_probe_rejected(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=1, window_seconds=10, open_seconds=1)
    advance(now_seq, 0.0)
    cb.on_failure()
    advance(now_seq, 2.0)
    cb.before_call()  # first probe accepted
    with pytest.raises(CircuitOpenError):
        cb.before_call()  # concurrent probe rejected


def test_window_expires_failure(now_seq: list[float]) -> None:
    cb = CircuitBreaker(fails_to_open=3, window_seconds=5, open_seconds=10)
    advance(now_seq, 0.0)
    cb.on_failure()
    advance(now_seq, 6.0)  # past the window
    cb.on_failure()
    # Only the most recent failure should remain in the window — circuit stays closed.
    assert cb.state == "closed"
