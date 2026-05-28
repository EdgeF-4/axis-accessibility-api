# ADR-0004 — Embeddings: local sentence-transformers, 384 dimensions

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** EdgeF-4
- **Supersedes:** —
- **Superseded by:** —

## Context

The Phase 6 deliverable is the "find venues with a similar accessibility
profile" path. ARCHITECTURE.md §12 listed the embedding-provider choice
as a deferred decision. Three forces shape it:

1. **Decoupling from Anthropic's pricing.** The extraction provider is
   already vendor-locked behind the `ExtractorProvider` Protocol; we do
   not want a second vendor multiplier on the per-datapoint cost.
2. **Latency budget.** The ingestion worker writes one datapoint and one
   embedding per (venue, attribute) cell. With ~37 attributes in the
   seeded taxonomy, a partner blob can produce 30+ embeddings; a
   network round-trip per write doubles the worker's serial time.
3. **Operational simplicity.** We are committed to one Postgres for
   storage + FTS + vectors (ADR-0001). The corollary should be one
   inference path that does not require an external service.

## Decision

Embeddings are produced by **`sentence-transformers/all-MiniLM-L6-v2`**
running in-process. The model is loaded lazily on first use, lives for
the process lifetime, and emits **384-dimensional** vectors.

`axis.embeddings.EmbeddingProvider` is a Protocol. The production class
is `axis.embeddings.local.LocalEmbedder`; a `FakeEmbedder` (deterministic
hash-derived vectors) is used in tests. The vector type on
`datapoints.embedding` is `vector(384)` (already pre-locked at the
Phase-1 schema; this ADR is the formal lock).

## Alternatives Considered

- **Anthropic embeddings.** Tied us to a second Anthropic call per
  datapoint; cost and latency both compound. Rejected.
- **OpenAI `text-embedding-3-small` (1536-dim).** Better quality on
  many benchmarks, but the same vendor-network-cost objection applies,
  and the larger dimension makes HNSW indexes heavier. Rejected for v1;
  a future ADR may revisit.
- **`all-mpnet-base-v2` (768-dim).** Higher quality at the same vendor-
  free cost, but ~3× the inference latency and 2× the vector storage.
  v1 favours throughput over per-fact recall; revisit at scale.
- **Manual TF-IDF / BM25 only.** We already have Postgres FTS for keyword
  similarity; the requirements specifically call out semantic similarity
  beyond keyword. Rejected.
- **Run sentence-transformers in a sidecar service.** Adds another
  service to the compose file and another network hop without gain at
  this scale. Rejected.

## Consequences

**Positive**
- No external dependency on the search hot path; the worker is
  self-contained.
- Inference is CPU-only by default; sentence-transformers will use a
  GPU if one is present without code changes.
- Swappable: another local model, OpenAI, or Anthropic embeddings is
  one new file under `axis.embeddings.*` and a settings flip.

**Negative / accepted tradeoffs**
- The container image is heavier — `sentence-transformers` pulls
  `torch`, which is ~300 MB. Acceptable for a worker image; the API
  image only loads the embedder if it falls back to inline embedding
  (it does not by default).
- The first inference after worker start pays a model-load cost
  (~2 s for MiniLM on CPU). Subsequent inferences are batched and
  fast. The cold start is acceptable for a worker that runs persistent.
- Storage cost: `vector(384)` is ~1.5 KB per datapoint. At 1 M
  datapoints, ≈ 1.5 GB of vectors plus the HNSW index. Within
  comfortable Postgres budget at v1 scale.

**Reversibility**
- Low cost. The provider Protocol means a swap is one new file plus a
  migration that recreates the column with the new dimension (and a
  one-time backfill). No production-data path changes.
