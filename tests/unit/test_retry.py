"""Retry with jittered exponential backoff."""

from __future__ import annotations

from typing import Any

import pytest

from axis.ingestion.retry import RetryableProviderError, with_retry


class _Recorder:
    """Capture sleep delays without actually sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _ceil_jitter(low: float, high: float) -> float:
    """Deterministic jitter for tests: return the upper bound."""
    assert low == 0.0
    return high


@pytest.mark.asyncio
async def test_succeeds_first_try_no_sleep() -> None:
    sleep = _Recorder()

    async def work() -> int:
        return 42

    result = await with_retry(
        work,
        max_attempts=3,
        base_seconds=1.0,
        max_seconds=10.0,
        sleep=sleep,
        jitter=_ceil_jitter,
    )
    assert result == 42
    assert sleep.sleeps == []


@pytest.mark.asyncio
async def test_retries_until_success() -> None:
    sleep = _Recorder()
    calls = {"n": 0}

    async def work() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableProviderError("boom")
        return "ok"

    result = await with_retry(
        work,
        max_attempts=5,
        base_seconds=2.0,
        max_seconds=10.0,
        sleep=sleep,
        jitter=_ceil_jitter,
    )
    assert result == "ok"
    # Ceiling-jitter == base * 2^(attempt-1), capped at max.
    assert sleep.sleeps == [2.0, 4.0]


@pytest.mark.asyncio
async def test_exhausts_budget_and_raises() -> None:
    sleep = _Recorder()

    async def work() -> Any:
        raise RetryableProviderError("nope")

    with pytest.raises(RetryableProviderError):
        await with_retry(
            work,
            max_attempts=3,
            base_seconds=1.0,
            max_seconds=10.0,
            sleep=sleep,
            jitter=_ceil_jitter,
        )
    # Two sleeps between three attempts.
    assert len(sleep.sleeps) == 2


@pytest.mark.asyncio
async def test_backoff_caps_at_max_seconds() -> None:
    sleep = _Recorder()

    async def work() -> Any:
        raise RetryableProviderError("again")

    with pytest.raises(RetryableProviderError):
        await with_retry(
            work,
            max_attempts=5,
            base_seconds=8.0,
            max_seconds=10.0,
            sleep=sleep,
            jitter=_ceil_jitter,
        )
    # Ceilings: 8, 16->10, 32->10, 64->10
    assert sleep.sleeps == [8.0, 10.0, 10.0, 10.0]


@pytest.mark.asyncio
async def test_non_retryable_passes_through_immediately() -> None:
    sleep = _Recorder()

    async def work() -> Any:
        raise RuntimeError("non-retryable")

    with pytest.raises(RuntimeError):
        await with_retry(
            work,
            max_attempts=5,
            base_seconds=1.0,
            max_seconds=10.0,
            sleep=sleep,
            jitter=_ceil_jitter,
        )
    assert sleep.sleeps == []
