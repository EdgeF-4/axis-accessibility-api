# ADR-0001 — Stack Selection

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** Enrique C. (architect)
- **Supersedes:** —
- **Superseded by:** —

## Context

AXIS is an Accessibility Intelligence API over a non-trivial domain:
structured accessibility data, LLM-based extraction, and semantic search.
I lock the stack early to avoid late-phase rewrites driven by tool envy and
to keep the data plane — constraints, FTS, vectors, migrations — in one
engine.

Three forces shape the choice:

1. **LLM as a first-class component.** Extraction via the LLM is core, not
   bolted on. The stack must support clean adapter interfaces, mocked
   testing, and observability around the LLM call.
2. **Production-realistic data plane.** Constraints, FTS, vectors, and
   migrations must all live in the same database to avoid the "demo with
   Elasticsearch we never deployed" smell.
3. **One-command developer experience.** A newcomer should `docker compose
   up` and hit a working API in under five minutes.

## Decision

The stack below is selected and locked. Substitutions require a new ADR
that supersedes this one.

| Concern              | Choice                                                | Rationale (one line)                                              |
| -------------------- | ----------------------------------------------------- | ----------------------------------------------------------------- |
| Language             | **Python 3.12**                                        | Modern typing (PEP 695, `Self`), async-mature, ML/AI ergonomics. |
| Web framework        | **FastAPI**                                            | Async, OpenAPI-native, Pydantic-first, type-driven.               |
| ORM                  | **SQLAlchemy 2.0 (async)**                             | Typed mappers (`Mapped[...]`), the senior standard.               |
| Migrations           | **Alembic**                                            | Versioned, autogenerate, rollforward discipline.                  |
| Edge validation      | **Pydantic v2**                                        | Strict types at HTTP boundary; codegen for LLM JSON schemas.      |
| Database             | **PostgreSQL 16 + pgvector**                           | Constraints, tsvector, vector search in one engine.               |
| Keyword search       | **Postgres FTS (tsvector + GIN)**                      | One engine; no Elastic ops cost for a flagship.                   |
| Semantic search      | **pgvector (HNSW)**                                    | Co-located with venue rows; transactional consistency.            |
| Cache / broker       | **Redis 7**                                            | Standard, supported by ARQ, fits slowapi rate limiting.           |
| Background jobs      | **ARQ**                                                | Async-native, lighter and clearer than Celery.                    |
| LLM provider         | **Anthropic Claude** via `ExtractorProvider` adapter    | Strict JSON-mode capable; swap behind interface.                  |
| AuthN                | **OAuth2 password + JWT (RS256) + refresh rotation**   | Real auth with token-theft mitigation, not a header check.        |
| AuthZ                | **RBAC scopes via FastAPI dependency**                 | Single enforcement point, not scattered ifs.                      |
| Logging              | **structlog (JSON)**                                   | Correlation-id-friendly, easy to ship to a sink.                  |
| Tracing              | **OpenTelemetry → OTLP**                               | Vendor-neutral spans across API + worker.                         |
| Metrics              | **prometheus_client → `/metrics`**                     | Industry-standard exposition.                                     |
| Rate limiting        | **slowapi (Redis-backed)**                             | Distributed; integrates with FastAPI dependencies.                |
| Tests                | **pytest + pytest-asyncio + testcontainers + httpx**   | Real Postgres in CI; no SQLite-coverage theater.                  |
| Lint / type          | **ruff + mypy --strict**                               | Fast; ruff replaces flake8/isort/black; mypy strict is mandatory. |
| Container            | **Docker + docker-compose**                            | One-command up; mirrors prod topology.                            |
| CI                   | **GitHub Actions**                                     | Free, integrated, badge-ready.                                    |

## Alternatives Considered

- **Django + DRF** — would force sync ORM patterns and a heavier template
  layer the project does not need. The async story is still bolt-on.
  *Rejected.*
- **NestJS / TypeScript** — strong typing and good DX, but the Python data /
  pgvector / async-worker ecosystem is the better fit for a data + AI
  extraction pipeline, and its async-ORM support is more mature.
  *Rejected.*
- **Celery (over ARQ)** — battle-tested, but its sync core and broker
  surface are heavier than needed. ARQ matches the rest of the async stack
  and keeps the worker module compact and readable.
  *Rejected for v1; reconsider if scheduled-task complexity grows.*
- **Elasticsearch / OpenSearch for FTS** — overkill for a single-service
  product; adds an ops surface without payoff at this scale.
  Postgres FTS + pgvector covers both axes in one engine.
  *Rejected.*
- **Pinecone / Qdrant / Weaviate for vectors** — same reasoning as above;
  pgvector is materially good enough at this scale and keeps the
  reconciliation transaction atomic.
  *Rejected.*
- **OpenAI / Bedrock for extraction** — the adapter interface makes this a
  one-file swap; Anthropic is the primary on quality of strict-JSON output
  and tool use. The interface is the commitment, not the provider.
  *Deferred behind `ExtractorProvider`.*
- **Poetry vs Hatch vs uv** — `uv` for installs in CI, `hatch` for
  build/scripts is plausible. Decision deferred to Phase 0 implementation
  choice; recorded if it deviates from a plain `pip + pyproject.toml`.

## Consequences

**Positive**

- One database engine to operate; one query language across keyword and
  vector search; transactional consistency between datapoints and their
  embeddings.
- Async throughout, including the worker, gives a coherent profiling story
  and clean OTel span propagation.
- Strict typing (`mypy --strict`) is enforceable in CI, raising the
  quality bar across the codebase.

**Negative / accepted tradeoffs**

- Postgres FTS is less feature-rich than Elasticsearch (no learn-to-rank,
  weaker multilingual analyzers). Acceptable at this scale; revisit if a
  partner demands multi-language stemming.
- pgvector HNSW indexes have build/insert cost; embeddings are written
  per datapoint, so we pay it incrementally rather than in batch. Index
  parameters (`m`, `ef_construction`) are tuned in Phase 6.
- ARQ has a smaller community than Celery; if scheduled-task semantics
  outgrow it, migrate to Celery + Redbeat. This is a swap-cost we accept.
- Tying to Anthropic for v1 is a single-vendor exposure; the
  `ExtractorProvider` interface plus a `FakeExtractor` for tests bounds
  the blast radius of that risk.

**Reversibility**

- Web framework, ORM, DB: high cost to swap; treated as terminal choices.
- Broker, rate limiter, observability sink: medium cost; documented swap
  paths.
- LLM provider, embedding provider: low cost behind their adapters; a swap
  is one new file + one config change.
