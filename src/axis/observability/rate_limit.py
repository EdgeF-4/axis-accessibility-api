"""Rate limiting via slowapi (Redis-backed).

Two limits, tunable via settings:

* :attr:`axis.config.Settings.ratelimit_default` — the global default
  applied to every route (e.g. ``100/minute``).
* :attr:`axis.config.Settings.ratelimit_auth` — tighter cap on the
  authentication endpoints to slow credential-stuffing.

The limiter is constructed lazily so :func:`axis.main.create_app` can
mount it; tests can replace the storage URI with ``memory://``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.util import get_remote_address

from axis.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterable

_LIMITER: Limiter | None = None


def get_limiter() -> Limiter:
    """Return the process-wide limiter, constructing on first call."""
    global _LIMITER
    if _LIMITER is None:
        s = get_settings()
        # ``slowapi`` accepts any RFC-3986-shaped URI; redis:// works in
        # production, memory:// is used by tests via AXIS_REDIS_URL override.
        _LIMITER = Limiter(
            key_func=get_remote_address,
            default_limits=[s.ratelimit_default],
            storage_uri=s.redis_url,
        )
    return _LIMITER


def reset_limiter() -> None:
    """For tests that need a fresh limiter (e.g. after settings reset)."""
    global _LIMITER
    _LIMITER = None


def auth_limits() -> Iterable[str]:
    """Stricter limit applied to /auth/* endpoints."""
    return [get_settings().ratelimit_auth]
