"""DLQ replay endpoint.

A DLQ'd job carries the full original payload in ``dlq_entries.payload``.
Replaying it moves the job back to ``QUEUED`` and zeros the attempts
counter; the worker (or an inline run) processes it again.

The replay endpoint never deletes the DLQ row — even after a successful
re-run, the audit trail of "this job failed and was retried at <time>
by <admin>" is preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from axis.api.v1.deps import DBSession, Principal, require_scope
from axis.db.models import DLQEntry, IngestionJob
from axis.db.models.enums import JobStatus

router = APIRouter(prefix="/dlq", tags=["ingestion"])


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    new_status: JobStatus


@router.post(
    "/{job_id}/replay",
    response_model=ReplayResult,
    dependencies=[Depends(require_scope("ingest:run"))],
)
async def replay_dlq(
    job_id: UUID,
    session: DBSession,
    principal: Principal,
) -> ReplayResult:
    """Reset a DLQ'd job to QUEUED for re-processing."""
    dlq = (
        await session.execute(select(DLQEntry).where(DLQEntry.job_id == job_id))
    ).scalar_one_or_none()
    if dlq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no DLQ entry for that job_id",
        )
    job = await session.get(IngestionJob, job_id)
    if job is None:
        # Should be impossible given the FK, but be defensive.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    job.status = JobStatus.QUEUED
    job.attempts = 0
    job.error = f"replay by {principal.subject_id} at {datetime.now(UTC).isoformat()}"
    job.started_at = None
    job.finished_at = None
    return ReplayResult(job_id=job.id, new_status=job.status)
