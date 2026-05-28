"""The Anthropic implementation of :class:`ExtractorProvider`.

This is the only file in the codebase allowed to import the Anthropic SDK.
The import-discipline test enforces that boundary; see ADR-0003.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anthropic
from pydantic import ValidationError

from axis.config import get_settings
from axis.extraction.prompts import SYSTEM_PROMPT, render_user_message
from axis.extraction.schemas import (
    CandidateDatapoint,
    ExtractionResult,
    UnknownAttribute,
)

if TYPE_CHECKING:
    from axis.extraction.provider import TaxonomySnapshot


class AnthropicProviderError(Exception):
    """Raised on a non-recoverable parse / API error.

    Transient errors (rate limit, 5xx, timeout) propagate as the SDK's
    native exception types so the retry policy can pattern-match them.
    """


class AnthropicExtractor:
    """Strict-JSON extraction via the Anthropic Messages API.

    The constructor accepts an optional ``client`` (for tests that inject
    a stub) and ``model`` (overrides settings). All other knobs flow from
    :func:`axis.config.get_settings`.
    """

    def __init__(
        self,
        *,
        client: anthropic.AsyncAnthropic | None = None,
        model: str | None = None,
        max_tokens: int = 1_500,
    ) -> None:
        s = get_settings()
        self._client = client or anthropic.AsyncAnthropic(
            api_key=s.anthropic_api_key.get_secret_value() or None,
        )
        self._model = model or s.extraction_model
        self._max_tokens = max_tokens

    async def extract(self, *, text: str, taxonomy: TaxonomySnapshot) -> ExtractionResult:
        """Call Claude, parse the JSON, classify candidates against ``taxonomy``."""
        user_message = render_user_message(text, taxonomy)
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_text = _join_text_blocks(message)
        return self._parse_response(raw_text, taxonomy, message)

    # --- internals ----------------------------------------------------------

    def _parse_response(
        self,
        raw_text: str,
        taxonomy: TaxonomySnapshot,
        message: Any,
    ) -> ExtractionResult:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise AnthropicProviderError(f"extractor returned non-JSON: {exc}") from exc

        raw_candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(raw_candidates, list):
            raise AnthropicProviderError("extractor JSON missing 'candidates' array")

        known: list[CandidateDatapoint] = []
        unknowns: list[UnknownAttribute] = []
        allowed = taxonomy.attribute_keys()
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue  # silently skip non-object entries; counts in metrics later
            key = str(raw.get("attribute_key") or "")
            try:
                if key in allowed:
                    known.append(CandidateDatapoint.model_validate(raw))
                else:
                    unknowns.append(
                        UnknownAttribute(
                            attribute_key=key,
                            value=raw.get("value", ""),
                            confidence=float(raw.get("confidence", 0.0)),
                            evidence_text=raw.get("evidence_text"),
                        )
                    )
            except (ValidationError, TypeError, ValueError):
                # Candidate failed validation — surface in unknowns so a
                # curator can inspect; never silently swallowed.
                unknowns.append(
                    UnknownAttribute(
                        attribute_key=key or "<malformed>",
                        value=raw.get("value", ""),
                        confidence=0.0,
                        evidence_text=raw.get("evidence_text"),
                    )
                )

        usage = getattr(message, "usage", None)
        return ExtractionResult(
            candidates=known,
            unknown_attributes=unknowns,
            model_name=self._model,
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
        )


def _join_text_blocks(message: Any) -> str:
    """Concatenate the text content of an Anthropic Messages response."""
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()
