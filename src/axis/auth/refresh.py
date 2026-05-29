"""Refresh tokens with rotation + reuse-detection.

The flow:

1. **Issue** — on successful login, mint an opaque random string
   (``secrets.token_urlsafe(32)``), insert a :class:`RefreshToken` row with
   a fresh ``family_id`` and store the SHA-256 hash of the token. Hand the
   plaintext back to the client; never log it.

2. **Rotate** — when the client presents a refresh token, look it up by
   hash. If found, not revoked, not expired: mark the old row revoked,
   insert a new row carrying the same ``family_id`` and ``parent_id``
   pointing at the old row, and return the new plaintext.

3. **Reuse-detection** — if the presented token *is* already revoked, it
   is being replayed. Revoke the entire family. Force re-login.

The hash is SHA-256 (not argon2): refresh tokens are 32 bytes of
cryptographic randomness, so a constant-time lookup is sufficient and we
do not want to pay the argon2 cost on every API hit.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, select, update

from axis.config import Settings, get_settings
from axis.db.models import RefreshToken
from axis.ids import new_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RefreshError(Exception):
    """Raised when a refresh-token operation cannot succeed."""


class ReusedRefreshTokenError(RefreshError):
    """Raised when a revoked refresh token is presented; the family is revoked.

    The caller should respond 401 and require re-authentication.
    """


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """The plaintext and the persisted-row pair returned by :func:`issue`."""

    plaintext: str
    row: RefreshToken


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _mint_plaintext() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


async def issue(
    session: AsyncSession,
    *,
    user_id: UUID,
    settings: Settings | None = None,
    family_id: UUID | None = None,
    parent_id: UUID | None = None,
) -> IssuedRefreshToken:
    """Mint a new refresh token for ``user_id``.

    ``family_id`` defaults to a fresh UUID (new login); pass an existing
    one to continue a rotation chain (see :func:`rotate`).
    """
    s = settings or get_settings()
    plaintext = _mint_plaintext()
    row = RefreshToken(
        id=new_id(),
        user_id=user_id,
        token_hash=_hash_token(plaintext),
        family_id=family_id or uuid4(),
        parent_id=parent_id,
        expires_at=_now() + timedelta(seconds=s.refresh_token_ttl_seconds),
    )
    session.add(row)
    await session.flush()
    return IssuedRefreshToken(plaintext=plaintext, row=row)


async def rotate(
    session: AsyncSession,
    presented_plaintext: str,
    *,
    settings: Settings | None = None,
) -> IssuedRefreshToken:
    """Validate the presented token, rotate it, and return the new pair.

    Raises:
      :class:`RefreshError` if the token is unknown or expired.
      :class:`ReusedRefreshTokenError` if the token has already been rotated;
      this call has the side effect of revoking the entire family.
    """
    token_hash = _hash_token(presented_plaintext)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        raise RefreshError("unknown refresh token")
    now = _now()
    if existing.expires_at <= now:
        raise RefreshError("refresh token expired")
    if existing.revoked_at is not None:
        await revoke_family(session, existing.family_id)
        raise ReusedRefreshTokenError(f"refresh token reused; revoked family {existing.family_id}")
    # Atomic-ish rotate: revoke the old row, then issue a new one in the same family.
    existing.revoked_at = now
    await session.flush()
    return await issue(
        session,
        user_id=existing.user_id,
        settings=settings,
        family_id=existing.family_id,
        parent_id=existing.id,
    )


async def revoke_family(session: AsyncSession, family_id: UUID) -> int:
    """Revoke every non-revoked token in ``family_id``. Returns rows affected."""
    now = _now()
    stmt = (
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.flush()
    # session.execute() is typed Result[Any]; a DML statement yields a
    # CursorResult at runtime, which is where rowcount lives.
    return int(cast(CursorResult[Any], result).rowcount or 0)
