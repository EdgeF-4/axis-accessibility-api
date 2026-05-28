"""Health endpoints.

* ``/healthz`` — liveness. Always 200 unless the process is too broken to
  serve. No external dependencies are touched.
* ``/readyz`` — readiness. Checks DB reachability, the current alembic
  head, and Redis (when configured). 200 if all green; 503 with a body
  identifying the failing check otherwise.
"""

from __future__ import annotations

from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from axis.api.v1.deps import DBSession
from axis.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, Literal["ok"]]:
    """Process-up liveness probe. No I/O."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(session: DBSession) -> JSONResponse:
    """Check every dependency the request path needs."""
    checks: dict[str, str] = {}
    ok = True

    # --- Postgres reachability + alembic head ---
    try:
        await session.execute(text("SELECT 1"))
        head = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        if head is None:
            checks["db"] = "unmigrated"
            ok = False
        else:
            checks["db"] = f"ok (alembic={head})"
    except Exception as exc:
        checks["db"] = f"down: {exc.__class__.__name__}"
        ok = False

    # --- Redis ping (optional path; many local dev runs have no broker yet) ---
    try:
        client = aioredis.from_url(get_settings().redis_url)  # type: ignore[no-untyped-call]
        try:
            pong = await client.ping()
            checks["redis"] = "ok" if pong else "no pong"
            ok = ok and bool(pong)
        finally:
            await client.aclose()
    except Exception as exc:
        checks["redis"] = f"down: {exc.__class__.__name__}"
        ok = False

    payload = {"status": "ok" if ok else "degraded", "checks": checks}
    return JSONResponse(
        payload,
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
