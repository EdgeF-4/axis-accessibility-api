"""Ingestion-job endpoints — submit a job and inspect its state."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from axis.api.v1.deps import DBSession, require_scope
from axis.db.models import DLQEntry, IngestionJob, Venue
from axis.db.models.enums import JobStatus
from axis.ingestion.idempotency import IdempotencyConflictError, submit_ingestion

router = APIRouter(tags=["ingestion"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """Body for ``POST /venues/{venue_id}/ingest``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2_048)


class IngestAccepted(BaseModel):
    """202 response carrying the job id (or re-asserting an existing one)."""

    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    created: bool


class JobStatusOut(BaseModel):
    """Detailed status for ``GET /jobs/{id}``."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    status: JobStatus
    attempts: int
    venue_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: dict[str, object] | None
    dlq_present: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/venues/{venue_id}/ingest",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scope("ingest:run"))],
)
async def submit_ingest(
    venue_id: UUID,
    body: IngestRequest,
    session: DBSession,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=4, max_length=128)
    ] = None,
) -> IngestAccepted:
    """Enqueue an AI-ingestion job for ``venue_id``.

    Idempotency-Key is required; replaying the same key with the same body
    returns the existing job (status=200-equivalent body, same job_id).
    """
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    venue = await session.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="venue not found")

    try:
        job, created = await submit_ingestion(
            session,
            venue_id=venue_id,
            idempotency_key=idempotency_key,
            payload={"text": body.text, "source_url": body.source_url},
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return IngestAccepted(job_id=job.id, status=job.status, created=created)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusOut,
    dependencies=[Depends(require_scope("ingest:run"))],
)
async def get_job(job_id: UUID, session: DBSession) -> JobStatusOut:
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    dlq = (
        await session.execute(select(DLQEntry.id).where(DLQEntry.job_id == job_id))
    ).scalar_one_or_none()
    return JobStatusOut(
        id=job.id,
        status=job.status,
        attempts=job.attempts,
        venue_id=job.venue_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result=job.result,
        dlq_present=dlq is not None,
    )


# Re-export for the router include.
__all__ = ["router"]

# Silence unused-import for the JobStatus literal alias (used in the schema).
_ = Literal
