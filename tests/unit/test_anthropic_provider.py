"""``AnthropicExtractor`` — parse-side behavior with a stub Anthropic client.

The Anthropic SDK is the boundary; we never call it from tests. Instead a
:class:`_StubClient` returns a pre-baked Messages object so the adapter's
JSON parsing, taxonomy filtering, and unknown-attribute routing all run
end-to-end under unit-test speeds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from axis.db.models.enums import ValueType
from axis.extraction.anthropic_provider import (
    AnthropicExtractor,
    AnthropicProviderError,
)
from axis.extraction.provider import TaxonomyAttributeSpec, TaxonomySnapshot

# ---------------------------------------------------------------------------
# Stub Anthropic client
# ---------------------------------------------------------------------------


@dataclass
class _Block:
    text: str


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _Message:
    content: list[_Block]
    usage: _Usage


class _StubMessages:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def create(self, **_: Any) -> _Message:
        return _Message(
            content=[_Block(text=json.dumps(self._payload))],
            usage=_Usage(input_tokens=42, output_tokens=17),
        )


class _StubClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.messages = _StubMessages(payload)


def _taxonomy(keys: list[tuple[str, ValueType]]) -> TaxonomySnapshot:
    return TaxonomySnapshot(
        version="test",
        attributes=tuple(
            TaxonomyAttributeSpec(
                key=k,
                value_type=vt,
                label=k,
                unit=None,
                category_key="mobility",
            )
            for k, vt in keys
        ),
    )


def _build(payload: dict[str, Any]) -> AnthropicExtractor:
    return AnthropicExtractor(client=_StubClient(payload), model="fake-model")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_candidate_round_trips() -> None:
    extractor = _build(
        {
            "candidates": [
                {
                    "attribute_key": "step_free_entrance",
                    "value": True,
                    "confidence": 0.93,
                    "evidence_text": "step-free entrance",
                }
            ]
        }
    )
    result = await extractor.extract(
        text="There is a step-free entrance.",
        taxonomy=_taxonomy([("step_free_entrance", ValueType.BOOL)]),
    )
    assert len(result.candidates) == 1
    assert result.candidates[0].attribute_key == "step_free_entrance"
    assert result.candidates[0].confidence == 0.93
    assert result.unknown_attributes == []
    assert result.tokens_in == 42
    assert result.tokens_out == 17
    assert result.model_name == "fake-model"


@pytest.mark.asyncio
async def test_unknown_key_routed_to_unknowns_not_candidates() -> None:
    extractor = _build(
        {"candidates": [{"attribute_key": "zero_gravity_room", "value": True, "confidence": 0.9}]}
    )
    result = await extractor.extract(
        text="weird claim",
        taxonomy=_taxonomy([("step_free_entrance", ValueType.BOOL)]),
    )
    assert result.candidates == []
    assert len(result.unknown_attributes) == 1
    assert result.unknown_attributes[0].attribute_key == "zero_gravity_room"


@pytest.mark.asyncio
async def test_non_json_response_raises_provider_error() -> None:
    # _Block text is JSON-loadable only as a string here.
    class _BadMessages:
        async def create(self, **_: Any) -> _Message:
            return _Message(content=[_Block(text="not JSON")], usage=_Usage(0, 0))

    class _BadClient:
        def __init__(self) -> None:
            self.messages = _BadMessages()

    extractor = AnthropicExtractor(client=_BadClient(), model="fake-model")  # type: ignore[arg-type]
    with pytest.raises(AnthropicProviderError):
        await extractor.extract(text="x", taxonomy=_taxonomy([]))


@pytest.mark.asyncio
async def test_malformed_candidate_lands_in_unknowns() -> None:
    """A candidate whose schema parse fails goes to unknowns, never silently dropped."""
    extractor = _build(
        {
            "candidates": [
                # Missing 'confidence' → schema parse fails → routed to unknowns.
                {"attribute_key": "step_free_entrance", "value": True},
            ]
        }
    )
    result = await extractor.extract(
        text="x",
        taxonomy=_taxonomy([("step_free_entrance", ValueType.BOOL)]),
    )
    assert result.candidates == []
    assert len(result.unknown_attributes) == 1


@pytest.mark.asyncio
async def test_missing_candidates_array_raises() -> None:
    extractor = _build({"unexpected": "shape"})
    with pytest.raises(AnthropicProviderError):
        await extractor.extract(text="x", taxonomy=_taxonomy([]))


@pytest.mark.asyncio
async def test_non_dict_candidate_entries_are_skipped_silently() -> None:
    extractor = _build(
        {
            "candidates": [
                "not-an-object",
                42,
                {"attribute_key": "step_free_entrance", "value": True, "confidence": 0.9},
            ]
        }
    )
    result = await extractor.extract(
        text="x",
        taxonomy=_taxonomy([("step_free_entrance", ValueType.BOOL)]),
    )
    assert len(result.candidates) == 1
