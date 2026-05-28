"""Shared dependencies — DB session + authenticated principal + scope checks.

This is the **only** module that decides who the caller is or whether they
are allowed to perform an action. Endpoints never branch on credentials;
they declare ``Depends(require_scope("..."))`` and trust the result.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axis.auth.jwt import JWTError, decode_access_token
from axis.auth.principal import AuthenticatedPrincipal, PrincipalKind
from axis.auth.rbac import effective_scopes_for_user
from axis.db.base import get_session_factory
from axis.db.models import ApiKey, User

# Public token URL — populates the swagger UI's "Authorize" widget.
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped DB session, committing on clean exit."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


DBSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_principal(
    session: DBSession,
    bearer: Annotated[str | None, Depends(_oauth2)] = None,
    api_key: Annotated[str | None, Depends(_api_key_header)] = None,
) -> AuthenticatedPrincipal:
    """Resolve the request's :class:`AuthenticatedPrincipal`.

    Tries OAuth2 bearer first, then ``X-API-Key``. Returns 401 if neither
    yields a valid principal.
    """
    if bearer:
        return await _principal_from_jwt(session, bearer)
    if api_key:
        return await _principal_from_api_key(session, api_key)
    raise _unauthorized("missing credentials")


Principal = Annotated[AuthenticatedPrincipal, Depends(get_principal)]


def require_scope(scope: str) -> Callable[..., Coroutine[Any, Any, AuthenticatedPrincipal]]:
    """Return a dependency that 403s unless the principal carries ``scope``.

    Usage::

        @router.get("/venues", dependencies=[Depends(require_scope("venue:read"))])
    """

    async def _check(principal: Principal) -> AuthenticatedPrincipal:
        if not principal.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing scope: {scope}",
            )
        return principal

    _check.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return _check


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _principal_from_jwt(session: AsyncSession, token: str) -> AuthenticatedPrincipal:
    try:
        claims = decode_access_token(token)
    except JWTError as exc:
        raise _unauthorized(f"invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("token missing subject")
    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise _unauthorized("token subject is not a uuid") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("subject not found or inactive")

    # Prefer scopes from the token (already minted with caller's scopes);
    # fall back to re-resolving against the DB if the claim is missing.
    scopes = frozenset(claims.get("scopes") or ())
    if not scopes:
        scopes = await effective_scopes_for_user(session, user_id)

    return AuthenticatedPrincipal(
        kind=PrincipalKind.USER,
        subject_id=user.id,
        display=user.email,
        scopes=scopes,
    )


async def _principal_from_api_key(session: AsyncSession, presented: str) -> AuthenticatedPrincipal:
    key_hash = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise _unauthorized("invalid api key")
    return AuthenticatedPrincipal(
        kind=PrincipalKind.API_KEY,
        subject_id=row.id,
        display=row.owner_org or row.name,
        scopes=frozenset(row.scopes or ()),
    )
