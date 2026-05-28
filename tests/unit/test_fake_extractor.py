"""``FakeExtractor`` satisfies the :class:`ExtractorProvider` Protocol and
filters its scripted candidates against the taxonomy snapshot."""

from __future__ import annotations

import pytest

from axis.db.models.enums import ValueType
from axis.extraction import (
    CandidateDatapoint,
    ExtractorProvider,
    TaxonomySnapshot,
)
from axis.extraction.fake import FakeExtractor
from axis.extraction.provider import TaxonomyAttributeSpec


def _taxonomy(keys: list[str]) -> TaxonomySnapshot:
    return TaxonomySnapshot(
        version="test",
        attributes=tuple(
            TaxonomyAttributeSpec(
                key=k,
                value_type=ValueType.BOOL,
                label=k,
                unit=None,
                category_key="mobility",
            )
            for k in keys
        ),
    )


def test_fake_satisfies_protocol() -> None:
    assert isinstance(FakeExtractor(), ExtractorProvider)


@pytest.mark.asyncio
async def test_matches_substring_and_returns_only_taxonomy_keys() -> None:
    fake = FakeExtractor(
        responses={
            "step-free": [
                CandidateDatapoint(attribute_key="step_free_entrance", value=True, confidence=0.9),
                CandidateDatapoint(attribute_key="invented_key", value=True, confidence=0.9),
            ]
        }
    )
    result = await fake.extract(
        text="There is a step-free entrance.",
        taxonomy=_taxonomy(["step_free_entrance"]),
    )
    keys = {c.attribute_key for c in result.candidates}
    assert keys == {"step_free_entrance"}
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_raise_with_propagates() -> None:
    class BangError(RuntimeError):
        pass

    fake = FakeExtractor(raise_with=BangError)
    with pytest.raises(BangError):
        await fake.extract(text="anything", taxonomy=_taxonomy([]))
