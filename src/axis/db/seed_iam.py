"""Default IAM seeding — scopes and roles.

This is the catalog defined in ARCHITECTURE.md §7.2. The scopes are the
authorization atoms; the roles are the bundles granted to humans. Partner
API keys carry scopes directly (no role indirection) and are minted
through an admin command, not seeded here.

The seeder is idempotent: re-running leaves the existing rows untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from axis.db.models import Role, RoleScope, Scope
from axis.ids import new_id

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

# --- Scope catalog ----------------------------------------------------------

SCOPES: Final[Mapping[str, str]] = {
    "venue:read": "Read venues and their accessibility profile",
    "venue:write": "Create / update venues",
    "ingest:run": "Enqueue AI ingestion jobs",
    "review:resolve": "Resolve human-in-the-loop review items",
    "taxonomy:admin": "Mutate the controlled vocabulary",
    "partner:read": "Partner-only read paths (API-key-scoped)",
}

# --- Role -> scope catalog --------------------------------------------------

ROLES: Final[Mapping[str, tuple[str, frozenset[str]]]] = {
    "admin": ("Administrator", frozenset(SCOPES)),
    "editor": (
        "Editor",
        frozenset({"venue:read", "venue:write", "ingest:run", "review:resolve"}),
    ),
    "reviewer": ("Reviewer", frozenset({"venue:read", "review:resolve"})),
    "reader": ("Reader", frozenset({"venue:read"})),
    "partner": ("Partner", frozenset({"partner:read"})),
}


async def seed_iam(session: AsyncSession) -> None:
    """Idempotently seed the scope and role catalog into ``session``."""
    # --- scopes ---
    existing_scopes = set((await session.execute(select(Scope.name))).scalars())
    for name, label in SCOPES.items():
        if name not in existing_scopes:
            session.add(Scope(name=name, label=label))
    await session.flush()

    # --- roles ---
    for role_name, (role_label, scope_names) in ROLES.items():
        role = (
            await session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one_or_none()
        if role is None:
            role = Role(id=new_id(), name=role_name, label=role_label)
            session.add(role)
            await session.flush()
        # Ensure every required (role, scope) link exists.
        existing_links = set(
            (
                await session.execute(
                    select(RoleScope.scope_name).where(RoleScope.role_id == role.id)
                )
            ).scalars()
        )
        for scope_name in scope_names:
            if scope_name not in existing_links:
                session.add(RoleScope(role_id=role.id, scope_name=scope_name))
    await session.flush()
