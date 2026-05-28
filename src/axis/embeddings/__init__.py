"""Embedding adapters — Protocol + local + fake.

See ADR-0004. ``LocalEmbedder`` loads the sentence-transformers model
lazily on first call; ``FakeEmbedder`` produces deterministic hash-derived
vectors for tests.
"""

from __future__ import annotations

from axis.embeddings.fake import FakeEmbedder
from axis.embeddings.provider import EMBEDDING_DIM, EmbeddingProvider

__all__ = ["EMBEDDING_DIM", "EmbeddingProvider", "FakeEmbedder"]
