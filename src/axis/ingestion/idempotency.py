"""Idempotency-keyed job submission.

``POST /venues/{id}/ingest`` carries an ``Idempotency-Key`` header. The
helper here is the only place that decides whether that key is a new job
or an existing one. Replaying the same key on the same payload returns
the existing job id; replaying it on a different payload is a client
error (409) so the contract is unambiguous.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from axis.db.models import IngestionJob
from axis.db.models.enums import JobStatus
from axis.ids import new_id

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class IdempotencyConflictError(Exception):
    """Same idempotency key was used with a different payload."""


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


async def submit_ingestion(
    session: AsyncSession,
    *,
    venue_id: UUID,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[IngestionJob, bool]:
    """Upsert an :class:`IngestionJob` by idempotency key.

    Returns ``(job, created)`` — ``created`` is True iff a new row was
    inserted. Raises :class:`IdempotencyConflictError` if the same key is
    re-used with a *different* payload.
    """
    payload_with_meta = {
        "venue_id": str(venue_id),
        "payload_hash": _stable_payload_hash(payload),
        "payload": payload,
    }

    existing = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.input.get("payload_hash") != payload_with_meta["payload_hash"]:
            raise IdempotencyConflictError(
                f"idempotency_key {idempotency_key!r} reused with a different payload"
            )
        return existing, False

    job = IngestionJob(
        id=new_id(),
        venue_id=venue_id,
        idempotency_key=idempotency_key,
        status=JobStatus.QUEUED,
        input=payload_with_meta,
    )
    session.add(job)
    await session.flush()
    return job, True
