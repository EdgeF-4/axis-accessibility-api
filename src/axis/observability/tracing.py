"""OpenTelemetry tracing — span tree on the ingestion path.

The configuration is opt-in via :attr:`axis.config.Settings.otel_exporter`:

* ``none`` (default) — install a no-op tracer so spans are emitted but
  not exported. The pipeline still gets correlation ids and span
  durations in structlog; nothing is shipped.
* ``otlp`` — install the OTLP gRPC exporter pointing at
  :attr:`axis.config.Settings.otel_endpoint`.

The ingestion span tree promised in ARCHITECTURE.md §8:

    ingest.job (job_id)
    ├── ingest.extract
    ├── ingest.validate
    ├── ingest.reconcile
    ├── ingest.persist
    └── ingest.embed
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from axis.config import Settings, get_settings

_CONFIGURED = False


def configure_tracing(settings: Settings | None = None) -> None:
    """Wire the global TracerProvider once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    s = settings or get_settings()
    resource = Resource.create({"service.name": s.otel_service_name})
    provider = TracerProvider(resource=resource)

    if s.otel_exporter == "otlp":
        # Deferred import: opentelemetry-exporter-otlp drags grpc.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter: Any = OTLPSpanExporter(endpoint=s.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        # Local-only mode: spans created but not exported. Useful for tests
        # that want a non-null tracer without setting up an OTLP collector.
        provider.add_span_processor(SimpleSpanProcessor(_NoopExporter()))

    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def get_tracer(name: str) -> trace.Tracer:
    """Convenience wrapper — pass a stable name like ``axis.ingestion.pipeline``."""
    return trace.get_tracer(name)


class _NoopExporter(SpanExporter):
    """Span exporter that drops every batch; for the ``none`` setting."""

    def export(self, _spans: Any) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, _timeout_millis: int = 30_000) -> bool:
        return True
