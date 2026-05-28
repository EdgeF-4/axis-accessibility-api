"""Prompt rendering — schema shape + injection-safety surface."""

from __future__ import annotations

import json

from axis.db.models.enums import ValueType
from axis.extraction.prompts import (
    SYSTEM_PROMPT,
    render_attributes_block,
    render_user_message,
)
from axis.extraction.provider import TaxonomyAttributeSpec, TaxonomySnapshot


def _snapshot() -> TaxonomySnapshot:
    return TaxonomySnapshot(
        version="t",
        attributes=(
            TaxonomyAttributeSpec(
                key="step_free_entrance",
                value_type=ValueType.BOOL,
                label="Step-free entrance",
                unit=None,
                category_key="mobility",
            ),
            TaxonomyAttributeSpec(
                key="entrance_threshold_height_cm",
                value_type=ValueType.NUMERIC,
                label="Threshold height",
                unit="cm",
                category_key="mobility",
            ),
        ),
    )


def test_attributes_block_is_valid_json_array() -> None:
    block = render_attributes_block(_snapshot())
    data = json.loads(block)
    assert isinstance(data, list)
    assert {entry["attribute_key"] for entry in data} == {
        "step_free_entrance",
        "entrance_threshold_height_cm",
    }


def test_user_message_carries_text_and_catalogue() -> None:
    msg = render_user_message("A venue with a step-free entrance.", _snapshot())
    assert "step_free_entrance" in msg
    assert "A venue with a step-free entrance." in msg


def test_system_prompt_pins_taxonomy_obedience() -> None:
    assert "controlled taxonomy" in SYSTEM_PROMPT
    assert "do not invent" in SYSTEM_PROMPT
