"""Opaque-cursor round-trip + tamper detection."""

from __future__ import annotations

import pytest

from axis.api.v1.pagination import CursorError, decode_cursor, encode_cursor


def test_encode_decode_round_trip() -> None:
    values = ("2026-05-28T12:00:00+00:00", "01900000-0000-7000-8000-000000000001")
    encoded = encode_cursor(values)
    assert "." in encoded  # body.signature
    decoded = decode_cursor(encoded)
    assert decoded == list(values)


def test_tampered_signature_rejected() -> None:
    encoded = encode_cursor(("a", "b"))
    body, sig = encoded.rsplit(".", 1)
    forged = f"{body}.{'0' * len(sig)}"
    with pytest.raises(CursorError):
        decode_cursor(forged)


def test_tampered_body_rejected() -> None:
    encoded = encode_cursor(("a", "b"))
    body, sig = encoded.rsplit(".", 1)
    # Mutate the last body character; signature now mismatches.
    mutated = body[:-1] + ("A" if body[-1] != "A" else "B")
    with pytest.raises(CursorError):
        decode_cursor(f"{mutated}.{sig}")


def test_missing_signature_rejected() -> None:
    with pytest.raises(CursorError):
        decode_cursor("no-dot-here")


def test_malformed_base64_rejected() -> None:
    # A valid signature on garbage that does not decode as JSON.
    from axis.api.v1.pagination import _sign

    body = "not-base64!!!!"
    bad = f"{body}.{_sign(body)}"
    with pytest.raises(CursorError):
        decode_cursor(bad)
