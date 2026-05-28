"""Smoke test that the ARQ ``WorkerSettings`` and task are wired correctly.

We do not run the ARQ worker in tests (that requires a live Redis + queue)
but we verify the module imports cleanly and exposes the expected names.
"""

from __future__ import annotations

import axis.ingestion.tasks as tasks_mod


def test_worker_settings_advertises_run_ingestion() -> None:
    assert tasks_mod.run_ingestion in tasks_mod.WorkerSettings.functions


def test_worker_settings_has_a_job_timeout() -> None:
    assert isinstance(tasks_mod.WorkerSettings.job_timeout, int)
    assert tasks_mod.WorkerSettings.job_timeout > 0


def test_worker_settings_redis_url_from_settings() -> None:
    cfg = tasks_mod.WorkerSettings.get_redis_settings()
    assert "url" in cfg
    url = cfg["url"]
    assert isinstance(url, str)
    assert url.startswith("redis://")
