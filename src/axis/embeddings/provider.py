"""The :class:`EmbeddingProvider` Protocol.

A provider takes a list of strings and returns a list of equal-length
unit vectors. The dimension is fixed at 384 (ADR-0004); changing it
requires a new ADR and a schema migration of ``datapoints.embedding``.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

EMBEDDING_DIM: Final[int] = 384


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Vectorise text. Provider implementations live under :mod:`axis.embeddings`."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one ``EMBEDDING_DIM``-vector per input text, in order.

        Implementations should batch when supported; the caller is free
        to call ``embed`` on lists of size 1.
        """
        ...
