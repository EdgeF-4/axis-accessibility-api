"""Trivial accessors on ``TaxonomySnapshot`` that the pipeline relies on."""

from __future__ import annotations

from axis.db.models.enums import ValueType
from axis.extraction.provider import TaxonomyAttributeSpec, TaxonomySnapshot


def _snap() -> TaxonomySnapshot:
    return TaxonomySnapshot(
        version="1.0.0",
        attributes=(
            TaxonomyAttributeSpec(
                key="step_free_entrance",
                value_type=ValueType.BOOL,
                label="Step-free entrance",
                unit=None,
                category_key="mobility",
            ),
            TaxonomyAttributeSpec(
                key="door_width_cm",
                value_type=ValueType.NUMERIC,
                label="Door width",
                unit="cm",
                category_key="mobility",
            ),
        ),
    )


def test_attribute_keys_returns_frozenset() -> None:
    snap = _snap()
    keys = snap.attribute_keys()
    assert isinstance(keys, frozenset)
    assert keys == {"step_free_entrance", "door_width_cm"}


def test_value_type_of_known_returns_value_type() -> None:
    snap = _snap()
    assert snap.value_type_of("step_free_entrance") is ValueType.BOOL
    assert snap.value_type_of("door_width_cm") is ValueType.NUMERIC


def test_value_type_of_unknown_returns_none() -> None:
    snap = _snap()
    assert snap.value_type_of("not_a_real_key") is None
