# ADR-0003 — LLM scope: extraction only

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** EdgeF-4
- **Supersedes:** —
- **Superseded by:** —

## Context

Phase 4 brings an LLM into the data path. The temptation in projects like
this is to let the model do more than extract: route requests, generate
ids, decide whether a candidate "is the same as" an existing fact, propose
a schema change when an unknown attribute appears. Every one of these is a
plausible 50-line patch. Every one of them buys a non-determinism in a
place the architecture promised would be deterministic.

[ARCHITECTURE.md §2.1](../../ARCHITECTURE.md) formalises the principle:
*LLM-where-fuzzy, deterministic-everywhere-rigid.* This ADR turns the
principle into a binding decision the codebase enforces.

## Decision

The Anthropic SDK is permitted to be imported only from
``axis.extraction.*``. Inside that package, the model is allowed to do
exactly one thing: take an arbitrary text blob and return a list of
candidate datapoints **expressed as keys from the controlled taxonomy
that was passed in with the prompt**.

Outside that perimeter the LLM is invisible. Specifically:

| Concern                              | Owner                                 |
| ------------------------------------ | ------------------------------------- |
| Idempotency key handling             | `axis.ingestion.idempotency`          |
| Job state transitions                | `axis.ingestion.pipeline`             |
| Retry budget + jittered backoff      | `axis.ingestion.retry`                |
| Circuit breaker                      | `axis.ingestion.circuit`              |
| Confidence-based routing             | `axis.ingestion.pipeline`             |
| Reconciliation precedence            | `axis.domain.reconcile`               |
| Datapoint persistence                | `axis.ingestion.persist`              |
| Authorization scope checks           | `axis.api.v1.deps.require_scope`      |
| Schema / attribute identity          | `axis.db.models.taxonomy`             |
| Venue / user / job id minting        | `axis.ids.new_id` (UUID v7, ADR-0002) |

The boundary is enforced two ways:

1. **Structural:** `tests/test_import_discipline.py::test_anthropic_import_only_in_extraction`
   fails the build if `anthropic` is imported anywhere outside
   `axis.extraction`.
2. **Behavioural:** unknown attribute keys returned by the model are
   *flagged* in the review queue with `unknown_attribute=true`; they are
   never persisted to `datapoints`, regardless of confidence. The
   reconciliation rule is reached only after every candidate has cleared
   the taxonomy gate.

## Alternatives Considered

- **Let the LLM choose the destination venue.** Rejected — even a tiny
  hallucination produces a write against the wrong row. The endpoint
  always carries the `venue_id`; the model never sees ids.
- **Let the LLM propose new attributes** when its candidates don't match
  the taxonomy. Rejected for v1 — taxonomy expansion is a migration plus
  a seed update plus an ADR-bumping conversation, not an autopilot
  decision. Unknown attributes become review items; a curator can
  promote them later.
- **Re-rank reconciliation outcomes with the model.** Rejected — the
  precedence rule is documented and testable; an LLM in that loop turns
  it into noise.
- **Skip the boundary, ship faster.** Rejected — the import-discipline
  test costs us 12 lines and pays for itself the first time a contributor
  thinks "this would be easier if I just called Claude from the venue
  endpoint."

## Consequences

**Positive**
- Bugs in the model's output produce review items, not corrupt rows.
- The pipeline is deterministic outside `extract()` and is unit-testable
  with a `FakeExtractor`.
- Provider swap (Anthropic → OpenAI → local) is one file, behind the
  `ExtractorProvider` Protocol.

**Negative / accepted tradeoffs**
- The taxonomy is a hard contract on the model. A useful candidate whose
  key is a synonym of an existing attribute is rejected, not coerced. A
  small "alias map" inside `extraction.prompts` could mitigate this; it
  is not in v1 because the false-positive risk outweighs the convenience.
- The model is asked to emit strict JSON. Some completions will fail
  validation. The retry policy and circuit breaker (ARCHITECTURE.md §5.2)
  absorb this.

**Reversibility**
- High. Any decision the model is given today can be added without
  touching the persistence path, because the contract is the
  `ExtractorProvider` shape, not the provider's implementation.
