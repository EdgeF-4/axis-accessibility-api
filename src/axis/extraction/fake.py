"""Deterministic ``ExtractorProvider`` for tests.

Tests inject a :class:`FakeExtractor` configured with a fixed
text→candidates mapping. The pipeline can therefore be exercised end-to-
end against a real Postgres without any network call to Anthropic and
without exposing tests to model non-determinism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from axis.extraction.schemas import (
    CandidateDatapoint,
    ExtractionResult,
    UnknownAttribute,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from axis.extraction.provider import TaxonomySnapshot


@dataclass
class FakeExtractor:
    """An extractor whose output is fully scripted.

    ``responses`` maps a substring (matched against the call's ``text``) to
    a list of candidates; the first matching substring wins. Use
    ``raise_with`` to make ``extract()`` raise a specific exception class
    (for retry / circuit-breaker tests).
    """

    responses: dict[str, Iterable[CandidateDatapoint]] = field(default_factory=dict)
    unknowns: list[UnknownAttribute] = field(default_factory=list)
    raise_with: type[BaseException] | None = None
    calls: int = 0

    async def extract(self, *, text: str, taxonomy: TaxonomySnapshot) -> ExtractionResult:
        self.calls += 1
        if self.raise_with is not None:
            raise self.raise_with("fake extractor raised on demand")
        chosen: list[CandidateDatapoint] = []
        for needle, cands in self.responses.items():
            if needle in text:
                allowed = taxonomy.attribute_keys()
                chosen = [c for c in cands if c.attribute_key in allowed]
                break
        return ExtractionResult(
            candidates=chosen,
            unknown_attributes=list(self.unknowns),
            model_name="fake",
            tokens_in=len(text) // 4,
            tokens_out=len(chosen) * 12,
        )
