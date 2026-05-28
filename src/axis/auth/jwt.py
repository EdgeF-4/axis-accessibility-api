"""Access-token signing and verification.

Access tokens are short-lived JWTs (default 15 min) carrying the user's
subject id and effective scopes. ``iss`` and ``aud`` are pinned per
environment and verified on every decode — a token minted for one
deployment cannot be replayed against another.

The signing algorithm is set by :attr:`axis.config.Settings.jwt_alg`:

* ``HS256`` (development) — symmetric, the secret is :attr:`jwt_secret`.
* ``RS256`` (production) — asymmetric; :attr:`jwt_secret` holds the PEM
  private key (signing) and the matching public key is used to verify.
  For symmetric environments PyJWT accepts the same secret for both roles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict
from uuid import UUID, uuid4

import jwt

from axis.config import Settings, get_settings


class AccessTokenClaims(TypedDict, total=False):
    """The fields of a verified access token claim set."""

    sub: str
    scopes: list[str]
    jti: str
    iss: str
    aud: str
    exp: int
    iat: int
    nbf: int


class JWTError(Exception):
    """Raised when an access token fails any verification step."""


def issue_access_token(
    *,
    subject_id: UUID,
    scopes: list[str],
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[str, AccessTokenClaims]:
    """Mint a signed access token for ``subject_id`` carrying ``scopes``.

    Returns the encoded JWT plus the claims dict — useful for tests that
    want to assert ``iat`` / ``exp`` without round-tripping the verify path.
    """
    s = settings or get_settings()
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(seconds=s.access_token_ttl_seconds)
    claims: AccessTokenClaims = {
        "sub": str(subject_id),
        "scopes": list(scopes),
        "jti": str(uuid4()),
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    encoded = jwt.encode(
        dict(claims),
        s.jwt_secret.get_secret_value(),
        algorithm=s.jwt_alg,
    )
    return encoded, claims


def decode_access_token(
    token: str,
    *,
    settings: Settings | None = None,
    leeway_seconds: int = 0,
) -> AccessTokenClaims:
    """Verify ``token``, returning the claim set on success.

    Raises :class:`JWTError` on any failure — bad signature, wrong issuer
    or audience, expired, malformed.
    """
    s = settings or get_settings()
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[s.jwt_alg],
            issuer=s.jwt_issuer,
            audience=s.jwt_audience,
            leeway=leeway_seconds,
        )
    except jwt.PyJWTError as exc:
        raise JWTError(str(exc)) from exc
    # Narrow to the typed shape; bad keys are a misuse of this module, not a 401.
    return _coerce_claims(decoded)


def _coerce_claims(raw: dict[str, Any]) -> AccessTokenClaims:
    out: AccessTokenClaims = {}
    if "sub" in raw:
        out["sub"] = str(raw["sub"])
    if "iss" in raw:
        out["iss"] = str(raw["iss"])
    if "aud" in raw:
        out["aud"] = str(raw["aud"])
    if "jti" in raw:
        out["jti"] = str(raw["jti"])
    if "scopes" in raw and isinstance(raw["scopes"], list):
        out["scopes"] = [str(s) for s in raw["scopes"]]
    if "exp" in raw:
        out["exp"] = int(raw["exp"])
    if "iat" in raw:
        out["iat"] = int(raw["iat"])
    if "nbf" in raw:
        out["nbf"] = int(raw["nbf"])
    return out


# --- Helpers used by tests and admin tools -----------------------------------


def derive_expiry(*, now: datetime, ttl_seconds: int) -> datetime:
    """Return ``now`` + ``ttl_seconds`` as a UTC datetime."""
    return now + timedelta(seconds=ttl_seconds)


HS_ALG: Literal["HS256"] = "HS256"
RS_ALG: Literal["RS256"] = "RS256"
