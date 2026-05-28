"""structlog configuration — JSON output, request_id / trace_id contextvars.

The configuration is *idempotent*: calling :func:`configure_logging` more
than once is safe (process-init, tests, alembic env all call it).

Every record carries:
- ``timestamp`` (ISO-8601 UTC)
- ``level``
- ``logger`` (the module name passed to :func:`get_logger`)
- ``event`` (the call-site message)
- ``request_id`` (populated by :class:`ObservabilityMiddleware` per request)
- any kwargs passed to ``log.info(...)`` etc.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
)

if TYPE_CHECKING:
    from structlog.types import EventDict, WrappedLogger

_CONFIGURED = False
_REQUEST_ID: ContextVar[str | None] = ContextVar("axis_request_id", default=None)


def configure_logging(*, level: str = "INFO", json: bool = True) -> None:
    """Wire structlog. Subsequent calls are no-ops."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    logging.basicConfig(level=level, format="%(message)s")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _augment_with_request_id,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )


def _augment_with_request_id(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Add the contextvar request_id if not already present."""
    if "request_id" not in event_dict:
        rid = _REQUEST_ID.get()
        if rid:
            event_dict["request_id"] = rid
    return event_dict


def set_request_id(request_id: str) -> None:
    """Bind a request id for the current task context."""
    _REQUEST_ID.set(request_id)
    bind_contextvars(request_id=request_id)


def clear_request_id() -> None:
    _REQUEST_ID.set(None)
    clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a logger; calling without a name uses the caller's module."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]


# Re-export for convenience in modules that prefer the structlog API.
__all__ = [
    "clear_request_id",
    "configure_logging",
    "get_logger",
    "merge_contextvars",
    "set_request_id",
]
