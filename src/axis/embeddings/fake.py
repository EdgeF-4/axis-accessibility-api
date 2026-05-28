"""Deterministic embedder for tests.

Uses a 64-bit hash of the input string as a seed for a small numpy-free
PRNG that fills a 384-dimensional vector. Vectors are L2-normalised so
cosine similarity is a 1-to-1 mapping with dot product — the same
property the production sentence-transformers model offers.

Identical strings produce identical vectors. Similar strings (sharing
prefixes or substrings) do **not** produce similar vectors; this is by
design — tests should not depend on semantic equivalence we cannot
guarantee from a hash.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from axis.embeddings.provider import EMBEDDING_DIM


def _xorshift64(state: int) -> int:
    """One step of a 64-bit xorshift PRNG."""
    state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
    state ^= state >> 7
    state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
    return state & 0xFFFFFFFFFFFFFFFF


def _seed_from(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big") or 1


def _vector_for(text: str) -> list[float]:
    state = _seed_from(text)
    raw: list[float] = []
    for _ in range(EMBEDDING_DIM):
        state = _xorshift64(state)
        # Convert the 64-bit unsigned state to a value in [-1, 1).
        raw.append((state / float(1 << 63)) - 1.0)
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


@dataclass
class FakeEmbedder:
    """A test embedder whose output is a pure function of the input."""

    calls: int = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [_vector_for(t) for t in texts]
