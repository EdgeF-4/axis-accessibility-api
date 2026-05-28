# ADR-0002 — UUID v7 as the identifier strategy

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** EdgeF-4
- **Supersedes:** —
- **Superseded by:** —

## Context

AXIS uses a UUID as the primary key on every aggregate root (`venue`,
`datapoint`, `ingestion_job`, `user`, …). The default choice in most
SQLAlchemy / Postgres stacks is UUID v4 (random, 122 bits of entropy). It is
collision-free at any scale we care about — but it has two costs that matter
to this project:

1. **B-tree fragmentation.** Random UUIDs scatter inserts across the entire
   primary-key index. On a write-heavy ingestion path (every candidate becomes
   a `datapoint` row plus the embedding), this means page splits and an
   ever-growing index footprint.
2. **No temporal ordering.** Debugging an ingestion replay (or auditing a
   conflict chain across the `superseded_by_id` self-FK) is materially easier
   when "the older row" can be inferred from the id itself.

A 2024 IETF draft codified these tradeoffs as
[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562) version 7: a time-ordered
UUID with 48 bits of millisecond timestamp followed by 74 bits of randomness.
The wire format is identical to other UUID versions; only the byte layout
changes.

## Decision

Every UUID primary key in AXIS is generated as **UUID v7**, produced by the
`uuid-utils` library (`uuid_utils.compat.uuid7`, which returns a
stdlib-compatible `uuid.UUID`).

A single helper `axis.ids.new_id()` is the only call site in the codebase; SQL
DEFAULTs are not used for ID generation — they are emitted at the application
layer to keep the contract uniform across writers (API handler, worker, seed).

## Alternatives Considered

- **UUID v4 (Python stdlib `uuid.uuid4`)** — collision-safe, zero dependency.
  Rejected for the index-fragmentation reason above and because it discards a
  useful debugging signal.
- **Postgres `gen_random_uuid()` as column DEFAULT** — server-side generation
  removes the dep but is still UUID v4. Same rejection.
- **ULID** — also time-ordered (48 bits ms + 80 bits randomness), Crockford
  base32 textual form. Postgres lacks a native type; round-tripping requires
  a 26-character `text` column or a custom domain. UUID v7 carries the same
  time-ordering benefit with native `uuid` storage and stdlib compatibility.
  *Rejected.*
- **bigserial / sequence-backed `bigint`** — smaller, faster, single-writer
  ergonomic. Rejected because partner data import paths and offline workers
  need to mint ids without round-tripping to the DB, and because exposing
  monotonic integers in API URLs is an information-leak smell.
- **Hand-rolled UUID v7** — code is ~30 lines, but `uuid-utils` is Rust-backed,
  benchmarked, and maintained. Reinventing the wheel for an id helper is the
  kind of overreach the architecture explicitly rejects.

## Consequences

**Positive**

- Insert-time locality: rows created together cluster together in the index;
  page splits decline dramatically vs. v4.
- Replay / debugging: `ORDER BY id` is a usable proxy for creation order
  without a separate `created_at` index lookup, simplifying audit queries on
  the `superseded_by_id` chain.
- Native Postgres `uuid` type and 16-byte storage are preserved; no schema
  change vs. a v4 baseline.

**Negative / accepted tradeoffs**

- A new runtime dependency (`uuid-utils`). The library is small (Rust-built
  via PyO3 wheels for cpython 3.12) and has no transitive surface beyond its
  own bindings.
- 48 bits of timestamp + 74 bits of randomness < v4's 122 bits of entropy.
  The collision probability is still astronomically low at AXIS scale
  (≪10⁻¹⁵ at 10⁶ inserts/sec for years), but it is correctly noted.
- Embedded creation timestamp is *observable* in the id. For internal ids
  that is welcome (debugging); for any future externally-presented id we
  should consider whether the temporal leak is acceptable. The decision can
  be reversed per-aggregate by overriding `new_id()` if needed.

**Reversibility**

- Medium-low cost. Switching back to v4 is one helper change. Existing rows
  retain their v7 ids; the `uuid` type accommodates both.
