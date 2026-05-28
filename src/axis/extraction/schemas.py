"""Pydantic schemas for what an extractor returns.

These types are the contract a provider must satisfy. They are validated
**before** anything reaches reconciliation or the database — a Pydantic
parse failure is an extraction failure, not a silent data loss.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CandidateDatapoint(BaseModel):
    """A single proposed accessibility fact returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    attribute_key: str = Field(min_length=1, max_length=128)
    value: bool | float | str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_text: str | None = Field(default=None, max_length=2_000)
    evidence_span: tuple[int, int] | None = None


class UnknownAttribute(BaseModel):
    """A candidate whose ``attribute_key`` is not in the active taxonomy.

    These are flagged into the review queue (with ``unknown_attribute=true``)
    instead of being silently dropped — ARCHITECTURE.md §2.5.
    """

    model_config = ConfigDict(extra="forbid")

    attribute_key: str
    value: bool | float | str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_text: str | None = None


class ExtractionResult(BaseModel):
    """What :meth:`ExtractorProvider.extract` returns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: list[CandidateDatapoint] = Field(default_factory=list)
    unknown_attributes: list[UnknownAttribute] = Field(default_factory=list)
    model_name: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
