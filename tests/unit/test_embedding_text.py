"""``render_embedding_text`` — stable shape used by both pipeline + search."""

from __future__ import annotations

from axis.ingestion.embedding import render_embedding_text


def test_basic_shape_bool() -> None:
    s = render_embedding_text(
        attribute_label="Step-free entrance",
        value=True,
        evidence="No steps at the entrance.",
    )
    assert "Step-free entrance" in s
    assert "True" in s
    assert "No steps" in s


def test_basic_shape_numeric_no_evidence() -> None:
    s = render_embedding_text(
        attribute_label="Door width",
        value=90.0,
        evidence=None,
    )
    assert "Door width" in s
    assert "90" in s
    # No trailing evidence parens when evidence is None
    assert "(" not in s


def test_evidence_is_quoted_form() -> None:
    s = render_embedding_text(
        attribute_label="Roll-in shower",
        value=True,
        evidence="shower has no step",
    )
    assert "(shower has no step)" in s
