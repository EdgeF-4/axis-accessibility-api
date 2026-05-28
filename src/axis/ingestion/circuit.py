"""Process-local circuit breaker for the LLM provider.

States: CLOSED → OPEN (after ``fails_to_open`` failures within
``window_seconds``) → HALF_OPEN (after ``open_seconds`` elapse) → CLOSED
on the first half-open success, or OPEN again on a half-open failure.

The breaker is process-local and reset-on-restart. ARCHITECTURE.md §5.2
notes a Redis-mirrored state for cross-process visibility; that lands
in Phase 7 alongside the metrics exposition.
"""

from __future__ import annotations

import enum
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Final


class CircuitOpenError(Exception):
    """The circuit refused the call without invoking the provider."""


class _State(enum.StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_NOW: Final = time.monotonic


@dataclass
class CircuitBreaker:
    """Failure-window-based breaker."""

    fails_to_open: int = 5
    window_seconds: float = 60.0
    open_seconds: float = 30.0

    _state: _State = _State.CLOSED
    _opened_at: float = 0.0
    _half_open_in_flight: bool = False
    _failures: deque[float] = field(default_factory=deque)

    def before_call(self) -> None:
        """Raise :class:`CircuitOpenError` if the circuit forbids this call."""
        if self._state is _State.CLOSED:
            return
        now = _NOW()
        if self._state is _State.OPEN:
            if now - self._opened_at >= self.open_seconds:
                self._state = _State.HALF_OPEN
                self._half_open_in_flight = False
            else:
                raise CircuitOpenError("circuit open; cooling down")
        if self._state is _State.HALF_OPEN:
            if self._half_open_in_flight:
                raise CircuitOpenError("circuit half-open; probe already in flight")
            self._half_open_in_flight = True

    def on_success(self) -> None:
        """Record a successful call. Closes the circuit if half-open."""
        self._failures.clear()
        self._state = _State.CLOSED
        self._half_open_in_flight = False

    def on_failure(self) -> None:
        """Record a failure. May open the circuit."""
        if self._state is _State.HALF_OPEN:
            self._state = _State.OPEN
            self._opened_at = _NOW()
            self._half_open_in_flight = False
            return
        now = _NOW()
        self._failures.append(now)
        # Drop failures that fell out of the rolling window.
        while self._failures and now - self._failures[0] > self.window_seconds:
            self._failures.popleft()
        if len(self._failures) >= self.fails_to_open:
            self._state = _State.OPEN
            self._opened_at = now

    @property
    def state(self) -> str:
        return self._state.value
