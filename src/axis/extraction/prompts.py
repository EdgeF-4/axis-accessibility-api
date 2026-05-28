"""Prompt construction for the Anthropic adapter.

Kept in its own module so the wire shape (system prompt, schema preamble,
attribute-key catalogue) can evolve without rippling into the orchestrator
or the persistence layer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from axis.extraction.provider import TaxonomySnapshot

SYSTEM_PROMPT = (
    "You are an accessibility-data extraction engine.\n"
    "You receive a venue description and a closed list of structured "
    "accessibility attributes from a controlled taxonomy.\n"
    "Your job: emit a JSON array of candidate facts. Every fact MUST use an "
    "`attribute_key` from the supplied list — do not invent keys. Use the "
    "value_type the taxonomy specifies for that key. If the text does not "
    "support a confident assertion, omit it; do not guess.\n"
    "Output JSON only, no prose.\n"
)


def render_attributes_block(taxonomy: TaxonomySnapshot) -> str:
    """Return a JSON-formatted catalogue of allowed attribute keys."""
    items = [
        {
            "attribute_key": a.key,
            "value_type": a.value_type.value,
            "unit": a.unit,
            "category": a.category_key,
            "label": a.label,
        }
        for a in taxonomy.attributes
    ]
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False)


def render_user_message(text: str, taxonomy: TaxonomySnapshot) -> str:
    """Compose the per-call user message."""
    catalogue = render_attributes_block(taxonomy)
    return (
        f"ALLOWED ATTRIBUTES (do not invent any other key):\n{catalogue}\n\n"
        f"VENUE TEXT:\n{text}\n\n"
        "Return JSON of shape:\n"
        '{"candidates":[{"attribute_key":"...","value":<bool|number|string>,'
        '"confidence":<0..1>,"evidence_text":"<short quote>"}]}'
    )
