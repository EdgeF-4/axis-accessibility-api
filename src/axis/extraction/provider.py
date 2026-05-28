"""The :class:`ExtractorProvider` Protocol and the immutable taxonomy
snapshot the pipeline hands to every extraction.

The snapshot is the model's prompt context: the list of attribute keys it
is allowed to emit, along with their value-types. It is captured once per
job at the moment the job is dequeued, so a taxonomy change mid-batch
does not produce inconsistent outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from axis.db.models.enums import ValueType
    from axis.extraction.schemas import ExtractionResult


@dataclass(frozen=True, slots=True)
class TaxonomyAttributeSpec:
    """A single attribute the extractor is allowed to emit."""

    key: str
    value_type: ValueType
    label: str
    unit: str | None
    category_key: str


@dataclass(frozen=True, slots=True)
class TaxonomySnapshot:
    """An immutable view of the taxonomy passed to a provider."""

    version: str
    attributes: tuple[TaxonomyAttributeSpec, ...]

    def attribute_keys(self) -> frozenset[str]:
        return frozenset(a.key for a in self.attributes)

    def value_type_of(self, key: str) -> ValueType | None:
        for a in self.attributes:
            if a.key == key:
                return a.value_type
        return None


@runtime_checkable
class ExtractorProvider(Protocol):
    """Provider contract — fuzzy text in, strict candidates out."""

    async def extract(self, *, text: str, taxonomy: TaxonomySnapshot) -> ExtractionResult:
        """Return candidate datapoints for ``text`` constrained by ``taxonomy``.

        Implementations must never raise; transient provider failures should
        be surfaced as :class:`axis.ingestion.retry.RetryableProviderError`
        so the worker's backoff + circuit breaker take effect.
        """
        ...
