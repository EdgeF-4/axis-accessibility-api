# EdgeF-4

> **Solo, backend architect.** I build production data + AI
> systems: schema-first, typed end-to-end, observable, tested against the
> real database.

Looking for engineers who treat the LLM as one component in a larger
deterministic system — not as a way to skip the schema, the auth model,
or the migration story? That's the work here.

---

## Pinned

### [AXIS — Accessibility Intelligence API](https://github.com/EdgeF-4/axis-accessibility-api)

The structured-data + AI-extraction layer behind disability-aware search.
Turns unstructured venue prose into a typed, queryable accessibility
taxonomy with provenance, confidence, reconciliation, and semantic
similarity.

- **Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Postgres 16 + pgvector ·
  Redis · ARQ · Anthropic Claude · sentence-transformers · structlog ·
  OpenTelemetry · Prometheus · slowapi · ruff · mypy --strict**
- Built in deliberate phases, each documented with an architecture decision record.
- 169 tests on real Postgres + Redis via testcontainers + httpx ASGI
  transport. ≥85 % coverage, `mypy --strict` clean, zero un-justified `Any`.
- Architecture and ADRs all in repo —
  [`ARCHITECTURE.md`](https://github.com/EdgeF-4/axis-accessibility-api/blob/main/ARCHITECTURE.md),
  [`docs/adr/`](https://github.com/EdgeF-4/axis-accessibility-api/tree/main/docs/adr).

---

## How I work

- **Schema first, types throughout.** SQLAlchemy 2.0 typed mappers,
  Pydantic v2 at the edges, mypy --strict in CI. Every `Any` is justified
  inline or it doesn't ship.
- **Boring storage, sharp queries.** One Postgres for relational + FTS +
  vectors before I reach for a second store. Migrations are forward-only
  and round-trip-tested.
- **LLM only where the input is fuzzy.** Identity, persistence, auth, and
  reconciliation are deterministic code. The LLM is one adapter behind a
  Protocol, swappable in one file.
- **Tests against the real system.** Postgres in CI, ASGI through the
  real router, idempotency replay actually replayed.
- **Documented decisions.** Every load-bearing call lives in an ADR
  (MADR format), so the reasoning behind each phase is on the record.

---

## Currently building

[AXIS](https://github.com/EdgeF-4/axis-accessibility-api) is the
flagship. Future repos extend it: dataset adapters, partner ingestion
contracts, embedding-quality benchmarks.

---

## Reach

[Profile on GitHub](https://github.com/EdgeF-4) · MIT-licensed work ·
contracts welcome.
