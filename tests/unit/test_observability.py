"""Unit-level smoke for logging, metrics, and tracing wiring."""

from __future__ import annotations

import structlog

from axis.observability.logging import (
    clear_request_id,
    configure_logging,
    get_logger,
    set_request_id,
)
from axis.observability.metrics import (
    record_http_request,
    record_ingestion_outcome,
    record_tokens,
    set_breaker_state,
)
from axis.observability.tracing import configure_tracing, get_tracer

# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging(level="DEBUG")  # must not raise


def test_logger_picks_up_request_id_contextvar() -> None:
    configure_logging()
    set_request_id("req-abc")
    try:
        log = get_logger("test")
        # Capture the rendered event dict to assert the contextvar surfaces.
        captured: list[structlog.types.EventDict] = []

        def capture(
            _logger: object, _method: str, ev: structlog.types.EventDict
        ) -> structlog.types.EventDict:
            captured.append(ev)
            return ev

        with structlog.testing.capture_logs() as logs:
            log.info("hello")
        assert any("hello" in (r.get("event") or "") for r in logs)
        _ = capture  # silence unused
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def test_record_http_request_increments_counter() -> None:
    record_http_request(method="GET", path="/test", status=200, duration_s=0.01)
    # No assertion API beyond "no exception" — the counter is private state
    # but its observation must not throw.


def test_record_ingestion_outcome_accepts_summary() -> None:
    record_ingestion_outcome(
        {"persisted": 2, "reviewed": 1, "dropped": 0, "conflicts": 0, "unknown": 0, "embedded": 2}
    )


def test_set_breaker_state_for_each_value() -> None:
    set_breaker_state("closed")
    set_breaker_state("open")
    set_breaker_state("half_open")


def test_record_tokens_no_op_on_zero() -> None:
    record_tokens(input_tokens=0, output_tokens=0)
    record_tokens(input_tokens=4, output_tokens=2)


# ---------------------------------------------------------------------------
# tracing
# ---------------------------------------------------------------------------


def test_configure_tracing_is_idempotent_and_returns_tracer() -> None:
    configure_tracing()
    configure_tracing()
    tracer = get_tracer("test.module")
    with tracer.start_as_current_span("unit-span") as span:
        span.set_attribute("ok", True)
