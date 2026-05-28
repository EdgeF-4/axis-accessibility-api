"""The composite v1 router mounted under ``/api/v1`` by the app factory."""

from __future__ import annotations

from fastapi import APIRouter

from axis.api.v1.auth import router as auth_router
from axis.api.v1.health import router as health_router
from axis.api.v1.jobs import router as jobs_router
from axis.api.v1.taxonomy import router as taxonomy_router
from axis.api.v1.venues import router as venues_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(venues_router)
router.include_router(jobs_router)
router.include_router(taxonomy_router)
router.include_router(health_router)

__all__ = ["router"]
