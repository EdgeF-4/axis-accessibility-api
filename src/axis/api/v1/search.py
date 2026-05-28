"""Semantic search endpoint.

The default embedder is :class:`FakeEmbedder` in test environments and
the lazy-loaded :class:`LocalEmbedder` in production. The endpoint never
calls ``sentence-transformers`` at module-import time; the first request
pays the model-load cost (~2 s on CPU), subsequent requests are fast.
"""

from __future__ import annotations

import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from axis.api.v1.deps import DBSession, require_scope
from axis.db.queries.search import semantic_search_venues
from axis.embeddings.fake import FakeEmbedder
from axis.embeddings.provider import EmbeddingProvider

router = APIRouter(prefix="/venues/search", tags=["venues"])


# --- Embedder resolution -----------------------------------------------------


_PROVIDER: EmbeddingProvider | None = None


def _get_default_embedder() -> EmbeddingProvider:
    """Return the process-wide embedder.

    Test environments (``AXIS_ENV=development`` + ``AXIS_FAKE_EMBEDDER=1``,
    or simply pytest detection) prefer :class:`FakeEmbedder`. Production
    uses :class:`LocalEmbedder`.
    """
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    if os.environ.get("AXIS_FAKE_EMBEDDER") == "1" or "PYTEST_CURRENT_TEST" in os.environ:
        _PROVIDER = FakeEmbedder()
    else:
        from axis.embeddings.local import LocalEmbedder

        _PROVIDER = LocalEmbedder()
    return _PROVIDER


def reset_default_embedder() -> None:
    """For tests that want to start fresh."""
    global _PROVIDER
    _PROVIDER = None


# --- Schemas -----------------------------------------------------------------


class SemanticHitOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    venue_id: UUID
    name: str
    venue_type: str
    country_code: str
    distance: float = Field(description="Cosine distance — lower is more similar")


class SemanticSearchOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    items: list[SemanticHitOut]


# --- Endpoint ----------------------------------------------------------------


@router.get(
    "/semantic",
    response_model=SemanticSearchOut,
    dependencies=[Depends(require_scope("venue:read"))],
)
async def semantic_search(
    session: DBSession,
    q: Annotated[str, Query(min_length=1, max_length=2_000)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SemanticSearchOut:
    """Return venues with a similar accessibility profile to the query."""
    embedder = _get_default_embedder()
    vectors = await embedder.embed([q])
    hits = await semantic_search_venues(
        session, query_vector=vectors[0] if vectors else [], limit=limit
    )
    return SemanticSearchOut(
        query=q,
        items=[
            SemanticHitOut(
                venue_id=h.venue_id,
                name=h.name,
                venue_type=h.venue_type,
                country_code=h.country_code,
                distance=h.distance,
            )
            for h in hits
        ],
    )
