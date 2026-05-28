"""ARQ task entry-points + worker settings.

In production, ``arq axis.ingestion.tasks:WorkerSettings`` starts the
worker process. Each enqueued ``run_ingestion`` invocation drives one
job through the pipeline.

Tests do not exercise this module directly; they call
:func:`axis.ingestion.run_ingestion_job` inline. The ARQ wrapper here is
the production glue.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from axis.config import get_settings
from axis.ingestion.pipeline import run_ingestion_job


async def run_ingestion(_ctx: dict[str, Any], job_id: str) -> dict[str, int]:
    """ARQ task — drive job ``job_id`` end to end."""
    return await run_ingestion_job(UUID(job_id))


class WorkerSettings:
    """Discovery class for the ARQ runner: ``arq axis.ingestion.tasks:WorkerSettings``."""

    functions = (run_ingestion,)
    max_jobs = 4
    job_timeout = 300  # seconds; a single extraction must complete under this

    @staticmethod
    def get_redis_settings() -> dict[str, object]:
        return {"url": get_settings().redis_url}
