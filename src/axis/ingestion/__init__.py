"""AI ingestion pipeline.

Five stages (ARCHITECTURE.md §5.1), each idempotent, observable, retryable:

1. **Ingest** — upsert :class:`IngestionJob` by ``idempotency_key``.
2. **Extract** — :class:`ExtractorProvider.extract` (Anthropic adapter or fake).
3. **Validate** — filter candidates against the active taxonomy.
4. **Score & route** — confidence ≥ persist threshold → datapoint;
   review threshold ≤ confidence < persist → :class:`ReviewItem`; below
   review threshold → dropped *with a metric*.
5. **Reconcile + persist** — apply the precedence policy from
   :func:`axis.domain.reconcile`, write rows.

The orchestrator entry point is :func:`run_ingestion_job`. The ARQ task
wrapper in :mod:`axis.ingestion.tasks` is the production driver; tests
call the orchestrator directly with a :class:`FakeExtractor`.
"""

from __future__ import annotations

from axis.ingestion.circuit import CircuitBreaker, CircuitOpenError
from axis.ingestion.idempotency import submit_ingestion
from axis.ingestion.pipeline import run_ingestion_job
from axis.ingestion.retry import RetryableProviderError, with_retry

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "RetryableProviderError",
    "run_ingestion_job",
    "submit_ingestion",
    "with_retry",
]
