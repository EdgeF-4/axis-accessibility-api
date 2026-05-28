"""``FakeEmbedder`` — deterministic, normalised, conforms to the Protocol."""

from __future__ import annotations

import math

import pytest

from axis.embeddings import EMBEDDING_DIM, EmbeddingProvider, FakeEmbedder


def test_fake_satisfies_protocol() -> None:
    assert isinstance(FakeEmbedder(), EmbeddingProvider)


@pytest.mark.asyncio
async def test_dimension_is_locked() -> None:
    fake = FakeEmbedder()
    vectors = await fake.embed(["abc", "def"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


@pytest.mark.asyncio
async def test_vectors_are_unit_norm() -> None:
    fake = FakeEmbedder()
    [v] = await fake.embed(["roll-in shower"])
    norm = math.sqrt(sum(x * x for x in v))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


@pytest.mark.asyncio
async def test_identical_inputs_produce_identical_vectors() -> None:
    fake = FakeEmbedder()
    [a] = await fake.embed(["same"])
    [b] = await fake.embed(["same"])
    assert a == b


@pytest.mark.asyncio
async def test_distinct_inputs_produce_distinct_vectors() -> None:
    fake = FakeEmbedder()
    a, b = await fake.embed(["left", "right"])
    assert a != b


@pytest.mark.asyncio
async def test_empty_input_returns_empty_list() -> None:
    fake = FakeEmbedder()
    out = await fake.embed([])
    assert out == []
