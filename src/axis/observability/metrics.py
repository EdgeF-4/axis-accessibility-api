"""Prometheus metrics — exposition at ``/metrics``.

The metric set is small and stable so dashboards don't fight cardinality:

- ``axis_http_requests_total{method, path, status}`` — total HTTP requests
- ``axis_http_request_duration_seconds{method, path}`` — latency histogram
- ``axis_ingestion_outcomes_total{outcome}`` — persisted/reviewed/dropped/…
- ``axis_circuit_breaker_state{state}`` — 1 for the current breaker state, 0 else
- ``axis_extraction_tokens_total{direction}`` — input / output tokens used by Anthropic

Cardinality discipline: ``path`` is the registered route path (not the
raw URL), so each route contributes O(1) label combinations.
"""

from __future__ import annotations

from typing import Final

from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

_REQUESTS: Final = Counter(
    "axis_http_requests_total",
    "HTTP requests handled.",
    labelnames=("method", "path", "status"),
)
_REQUEST_DURATION: Final = Histogram(
    "axis_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
_INGESTION = Counter(
    "axis_ingestion_outcomes_total",
    "Ingestion candidate outcomes.",
    labelnames=("outcome",),
)
_BREAKER_STATE = Gauge(
    "axis_circuit_breaker_state",
    "Provider circuit breaker — 1 for the named state, 0 otherwise.",
    labelnames=("state",),
)
_TOKENS = Counter(
    "axis_extraction_tokens_total",
    "Tokens spent on the extraction provider.",
    labelnames=("direction",),
)


def record_http_request(*, method: str, path: str, status: int, duration_s: float) -> None:
    """Called once per request by :class:`ObservabilityMiddleware`."""
    _REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    _REQUEST_DURATION.labels(method=method, path=path).observe(duration_s)


def record_ingestion_outcome(summary: dict[str, int]) -> None:
    """Translate a pipeline summary into per-outcome counters."""
    for k, v in summary.items():
        _INGESTION.labels(outcome=k).inc(int(v))


def set_breaker_state(state: str) -> None:
    """Update the breaker gauge to reflect the named state."""
    for s in ("closed", "open", "half_open"):
        _BREAKER_STATE.labels(state=s).set(1 if s == state else 0)


def record_tokens(*, input_tokens: int, output_tokens: int) -> None:
    if input_tokens:
        _TOKENS.labels(direction="input").inc(input_tokens)
    if output_tokens:
        _TOKENS.labels(direction="output").inc(output_tokens)


def metrics_response() -> Response:
    """Render the current registry as a Prometheus text exposition."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
