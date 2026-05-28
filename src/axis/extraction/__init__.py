"""Fuzzy-input extraction adapter.

This is the **only** package in AXIS allowed to import the Anthropic SDK.
The import-discipline test (``tests/test_import_discipline.py``) fails
the build if that rule is broken. See ADR-0003 for the rationale.
"""

from __future__ import annotations

from axis.extraction.provider import ExtractorProvider, TaxonomySnapshot
from axis.extraction.schemas import (
    CandidateDatapoint,
    ExtractionResult,
    UnknownAttribute,
)

__all__ = [
    "CandidateDatapoint",
    "ExtractionResult",
    "ExtractorProvider",
    "TaxonomySnapshot",
    "UnknownAttribute",
]
