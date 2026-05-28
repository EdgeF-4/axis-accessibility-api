"""The composite v1 router mounted under ``/api/v1`` by the app factory."""

from __future__ import annotations

from fastapi import APIRouter

from axis.api.v1.auth import router as auth_router

router = APIRouter()
router.include_router(auth_router)

__all__ = ["router"]
