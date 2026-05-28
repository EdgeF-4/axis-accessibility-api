"""Logs, traces, metrics.

Three pillars:

* :mod:`axis.observability.logging` — structlog JSON, request_id +
  trace_id in every record.
* :mod:`axis.observability.tracing` — OpenTelemetry; the ingestion span
  tree promised in ARCHITECTURE.md §8.
* :mod:`axis.observability.metrics` — Prometheus exposition at
  ``/metrics``.

:mod:`axis.observability.middleware` is the FastAPI middleware that ties
the request_id / trace_id / latency-histogram pieces together. It is
mounted by :func:`axis.main.create_app`.
"""

from __future__ import annotations

from axis.observability.logging import configure_logging, get_logger
from axis.observability.metrics import metrics_response, record_ingestion_outcome
from axis.observability.middleware import ObservabilityMiddleware

__all__ = [
    "ObservabilityMiddleware",
    "configure_logging",
    "get_logger",
    "metrics_response",
    "record_ingestion_outcome",
]
