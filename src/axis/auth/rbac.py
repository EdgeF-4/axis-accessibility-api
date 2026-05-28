"""RBAC — resolve a user's effective scopes via their assigned roles.

The query is a single join across the four IAM tables and runs once per
authenticated request (or once per access-token mint, whichever comes
first — the cached path is the access-token's embedded scopes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from axis.db.models import RoleAssignment, RoleScope

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def effective_scopes_for_user(session: AsyncSession, user_id: UUID) -> frozenset[str]:
    """Return the set of scope names granted to ``user_id`` via their roles."""
    stmt = (
        select(RoleScope.scope_name)
        .join(RoleAssignment, RoleAssignment.role_id == RoleScope.role_id)
        .where(RoleAssignment.user_id == user_id)
        .distinct()
    )
    rows = (await session.execute(stmt)).scalars().all()
    return frozenset(rows)
