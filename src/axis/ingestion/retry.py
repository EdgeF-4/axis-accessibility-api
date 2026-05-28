"""Jittered exponential backoff for the extraction stage.

The retry layer is intentionally thin: it owns nothing except *deciding
when to wait and how long*. The work is supplied as an awaitable; the
caller (the orchestrator) decides what counts as retryable.

A retry budget is exhausted as soon as the await raises
:class:`RetryableProviderError` ``max_attempts`` times in a row; the
orchestrator catches the final exception and DLQs the job.
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


class RetryableProviderError(Exception):
    """Mark a failure as worth retrying.

    The Anthropic adapter wraps SDK exceptions (RateLimitError, APIStatusError
    with 5xx, APIConnectionError, APITimeoutError) in this class so the
    retry layer can pattern-match without depending on the SDK.
    """


async def with_retry[T](
    work: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    base_seconds: float,
    max_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> T:
    """Execute ``work``, retrying on :class:`RetryableProviderError`.

    The delay between attempts is uniformly random in ``[0, min(max,
    base * 2^(n-1))]`` — "full jitter", the formulation that avoids
    thundering herd while keeping the expected backoff close to the
    pure-exponential schedule.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await work()
        except RetryableProviderError as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            ceiling = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
            await sleep(jitter(0.0, ceiling))
    assert last_exc is not None  # noqa: S101 -- mypy narrowing only
    raise last_exc
