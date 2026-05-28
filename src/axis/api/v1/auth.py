"""Authentication endpoints — token issue, refresh rotation, logout."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select

from axis.api.v1.deps import DBSession, Principal
from axis.auth.jwt import issue_access_token
from axis.auth.passwords import verify_password
from axis.auth.principal import PrincipalKind
from axis.auth.rbac import effective_scopes_for_user
from axis.auth.refresh import (
    RefreshError,
    ReusedRefreshTokenError,
    issue as issue_refresh,
    revoke_family,
    rotate as rotate_refresh,
)
from axis.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TokenPair(BaseModel):
    """OAuth2-style token pair returned to the client."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 -- OAuth2 token-type literal, not a secret


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/token", response_model=TokenPair)
async def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DBSession,
) -> TokenPair:
    """OAuth2 password-flow login. Returns an access + refresh pair."""
    user = (
        await session.execute(select(User).where(User.email == form.username))
    ).scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    if not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    scopes = await effective_scopes_for_user(session, user.id)
    access, _ = issue_access_token(subject_id=user.id, scopes=sorted(scopes))
    refresh = await issue_refresh(session, user_id=user.id)
    return TokenPair(access_token=access, refresh_token=refresh.plaintext)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(body: RefreshRequest, session: DBSession) -> TokenPair:
    """Rotate the presented refresh token. Reusing a revoked token kills the family."""
    try:
        rotated = await rotate_refresh(session, body.refresh_token)
    except ReusedRefreshTokenError as exc:
        # The family-revocation side effect must survive even though we are
        # about to raise. Commit explicitly; the request-scoped session
        # otherwise rolls back on exception.
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token reused — family revoked",
        ) from exc
    except RefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    scopes = await effective_scopes_for_user(session, rotated.row.user_id)
    access, _ = issue_access_token(subject_id=rotated.row.user_id, scopes=sorted(scopes))
    return TokenPair(access_token=access, refresh_token=rotated.plaintext)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: Principal, body: RefreshRequest, session: DBSession) -> None:
    """Revoke the refresh-token family the caller is associated with.

    Requires authentication so an unauthenticated caller cannot grief other
    users by guessing token values. API-key principals don't have refresh
    families; this is a no-op (still 204) for them.
    """
    if principal.kind is PrincipalKind.API_KEY:
        return

    # Resolve the family from the presented refresh token so we revoke the
    # whole login session, not just this access token.
    import hashlib  # local import to keep top of module clean

    token_hash = hashlib.sha256(body.refresh_token.encode("utf-8")).hexdigest()
    from axis.db.models import RefreshToken  # local import to avoid top-level cycle

    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None or row.user_id != principal.subject_id:
        # Either the token is bogus or it does not belong to the caller —
        # do nothing rather than leak existence.
        return
    await revoke_family(session, row.family_id)
