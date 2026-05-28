"""FastAPI application factory.

``create_app()`` is the single construction point. Tests and the uvicorn
entry point both call it; nothing else builds a FastAPI instance.
"""

from __future__ import annotations

from fastapi import FastAPI

from axis import __version__
from axis.api.v1 import router as v1_router
from axis.config import get_settings
from axis.observability.logging import configure_logging
from axis.observability.metrics import metrics_response
from axis.observability.middleware import ObservabilityMiddleware
from axis.observability.tracing import configure_tracing


def create_app() -> FastAPI:
    """Return a fully-wired FastAPI app."""
    settings = get_settings()
    # Idempotent: subsequent calls (tests) are no-ops.
    configure_logging(level=settings.log_level)
    configure_tracing(settings)

    app = FastAPI(
        title="AXIS — Accessibility Intelligence API",
        version=__version__,
        description=(
            "Structured accessibility data + AI extraction for the physical "
            "world. See https://github.com/EdgeF-4/axis-accessibility-api."
        ),
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url="/redoc" if settings.env != "production" else None,
        openapi_url="/openapi.json",
    )

    # Request-id propagation + per-route latency histogram.
    app.add_middleware(ObservabilityMiddleware)

    app.include_router(v1_router, prefix="/api/v1")

    # Prometheus exposition at the un-versioned root so scrape configs do
    # not have to track API-version bumps.
    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> object:
        return metrics_response()

    return app


app = create_app()
