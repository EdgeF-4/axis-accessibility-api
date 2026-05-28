"""Local sentence-transformers embedder.

This module imports ``sentence-transformers`` lazily on first call. The
model is loaded once per process and is thread-safe for inference. The
optional dependency is declared in ``pyproject.toml`` under the
``embeddings`` extra so the API image (which delegates embedding to the
worker) does not need to pull torch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from axis.embeddings.provider import EMBEDDING_DIM

_MODEL: Any = None
_LOAD_LOCK = asyncio.Lock()


async def _get_model(model_name: str) -> Any:
    """Load the sentence-transformers model on first call, then cache."""
    global _MODEL
    cached = _MODEL
    if cached is not None:
        return cached
    async with _LOAD_LOCK:
        # Double-checked locking: another coroutine may have populated
        # _MODEL while we were awaiting the lock.
        cached = _MODEL
        if cached is not None:
            return cached
        # Defer the heavy import so the API image does not pay torch's
        # import cost just to wire the provider Protocol.
        from sentence_transformers import SentenceTransformer

        loaded = await asyncio.to_thread(SentenceTransformer, model_name)
        # Verify the dimension matches what the schema agreed to.
        dim = int(loaded.get_sentence_embedding_dimension())
        if dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"model {model_name!r} produces {dim}-dim vectors; "
                f"AXIS schema is {EMBEDDING_DIM}-dim (ADR-0004)"
            )
        _MODEL = loaded
        return _MODEL


class LocalEmbedder:
    """sentence-transformers embedder running in-process.

    ``model_name`` defaults to ``sentence-transformers/all-MiniLM-L6-v2``
    (ADR-0004). Pass a different name only via a new ADR.
    """

    def __init__(self, *, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self._model_name = model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await _get_model(self._model_name)
        # ``encode`` is sync; run on a worker thread so we don't stall
        # the event loop. ``normalize_embeddings=True`` gives unit vectors.
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [list(map(float, v)) for v in vectors]
