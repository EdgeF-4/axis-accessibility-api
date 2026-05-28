"""JWT access-token issue / decode verification.

The tests exercise the contract every Phase 2+ feature relies on: issuer
and audience pinning, expiry enforcement, scope round-trip, tamper
detection. They use a freshly-built Settings rather than the cached
process-wide one so each case is isolated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from axis.auth.jwt import JWTError, decode_access_token, issue_access_token
from axis.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": SecretStr("test-secret"),
        "jwt_alg": "HS256",
        "jwt_issuer": "axis.test",
        "jwt_audience": "axis-api",
        "access_token_ttl_seconds": 900,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_issue_then_decode_round_trips_scopes_and_subject() -> None:
    s = _settings()
    sid = uuid4()
    token, claims = issue_access_token(
        subject_id=sid, scopes=["venue:read", "venue:write"], settings=s
    )
    decoded = decode_access_token(token, settings=s)
    assert decoded["sub"] == str(sid)
    assert decoded["scopes"] == ["venue:read", "venue:write"]
    assert decoded["iss"] == "axis.test"
    assert decoded["aud"] == "axis-api"
    assert claims["exp"] - claims["iat"] == 900


def test_wrong_secret_rejected() -> None:
    s = _settings()
    bad_secret = _settings(jwt_secret=SecretStr("evil"))
    token, _ = issue_access_token(subject_id=uuid4(), scopes=[], settings=s)
    with pytest.raises(JWTError):
        decode_access_token(token, settings=bad_secret)


def test_wrong_issuer_rejected() -> None:
    s = _settings()
    other_iss = _settings(jwt_issuer="other.test")
    token, _ = issue_access_token(subject_id=uuid4(), scopes=[], settings=s)
    with pytest.raises(JWTError):
        decode_access_token(token, settings=other_iss)


def test_wrong_audience_rejected() -> None:
    s = _settings()
    other_aud = _settings(jwt_audience="someone-else")
    token, _ = issue_access_token(subject_id=uuid4(), scopes=[], settings=s)
    with pytest.raises(JWTError):
        decode_access_token(token, settings=other_aud)


def test_expired_token_rejected() -> None:
    s = _settings()
    past = datetime.now(UTC) - timedelta(seconds=s.access_token_ttl_seconds + 60)
    token, _ = issue_access_token(subject_id=uuid4(), scopes=[], settings=s, now=past)
    with pytest.raises(JWTError):
        decode_access_token(token, settings=s)


def test_tampered_payload_rejected() -> None:
    s = _settings()
    token, _ = issue_access_token(subject_id=uuid4(), scopes=["venue:read"], settings=s)
    # Forge a new payload with elevated scopes but keep the original signature.
    header, _, signature = token.split(".")
    forged_payload = jwt.encode(
        {"sub": "x", "scopes": ["taxonomy:admin"], "iss": "axis.test", "aud": "axis-api"},
        "test-secret",
        algorithm="HS256",
    ).split(".")[1]
    forged = f"{header}.{forged_payload}.{signature}"
    with pytest.raises(JWTError):
        decode_access_token(forged, settings=s)
