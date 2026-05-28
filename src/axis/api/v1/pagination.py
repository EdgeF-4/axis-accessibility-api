"""Opaque, signed, tamper-evident cursors for list endpoints.

A cursor is a JSON-encoded ordered tuple, base64-url-encoded, followed by
``.`` and an HMAC-SHA256 prefix signed with :attr:`axis.config.Settings.jwt_secret`.

This gives us three properties for free:

* **opaque** — clients cannot guess the schema, so they cannot construct
  cursors out-of-band that skew pagination.
* **tamper-evident** — a flipped byte produces an invalid signature; the
  request is rejected with 400 rather than serving from a forged offset.
* **versionless** — the JSON shape can grow another column (e.g. add
  ``ranking_score`` for hybrid search) without breaking clients in the
  field, because cursors are only valid for one paging session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Final

from axis.config import get_settings

_SIG_LEN: Final[int] = 16  # 128 bits of HMAC prefix; plenty for tamper detection.


class CursorError(ValueError):
    """Raised when a cursor fails to decode or its signature does not match."""


def encode_cursor(values: tuple[object, ...]) -> str:
    """Encode an ordered tuple of cursor fields. Strings only (caller stringifies)."""
    body = (
        base64.urlsafe_b64encode(
            json.dumps([str(v) for v in values], separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    sig = _sign(body)
    return f"{body}.{sig}"


def decode_cursor(cursor: str) -> list[str]:
    """Inverse of :func:`encode_cursor`. Raises :class:`CursorError` on tamper."""
    try:
        body, sig = cursor.rsplit(".", 1)
    except ValueError as exc:
        raise CursorError("cursor missing signature") from exc
    expected = _sign(body)
    if not hmac.compare_digest(sig, expected):
        raise CursorError("cursor signature invalid")
    padded = body + "=" * (-len(body) % 4)
    try:
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CursorError("cursor body malformed") from exc
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise CursorError("cursor body has wrong shape")
    return list(raw)


def _sign(body: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()[:_SIG_LEN]
