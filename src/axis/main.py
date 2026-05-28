"""FastAPI application factory.

``create_app()`` is the single construction point. Tests and the uvicorn
entry point both call it; nothing else builds a FastAPI instance.
"""

from __future__ import annotations

from fastapi import FastAPI

from axis import __version__
from axis.api.v1 import router as v1_router
from axis.config import get_settings


def create_app() -> FastAPI:
    """Return a fully-wired FastAPI app."""
    settings = get_settings()

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

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
