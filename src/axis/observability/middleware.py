"""FastAPI middleware — request_id binding + latency metric.

For every HTTP request:

1. Generate or read an inbound ``X-Request-ID`` header.
2. Bind it as the structlog contextvar so every log line carries it.
3. Time the request; record a Prometheus histogram observation keyed by
   the route path (the FastAPI-resolved path template, not the raw URL).
4. Echo the request id back as ``X-Request-ID`` on the response.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from axis.observability.logging import clear_request_id, set_request_id
from axis.observability.metrics import record_http_request

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Tie request_id propagation to latency + counter metrics."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        set_request_id(request_id)

        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = time.perf_counter() - started
            # ``request.scope['route'].path`` is the route template (e.g.
            # ``/api/v1/venues/{venue_id}``). Falling back to the raw url
            # is acceptable for unmatched routes (404s and the like).
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or request.url.path
            status_code = response.status_code if response is not None else 500
            record_http_request(
                method=request.method,
                path=str(route_path),
                status=status_code,
                duration_s=elapsed,
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id
            clear_request_id()
