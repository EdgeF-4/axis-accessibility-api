"""Default IAM seeding — scopes, roles, role↔scope grants are idempotent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from axis.db.models import Role, RoleScope, Scope
from axis.db.seed_iam import ROLES, SCOPES, seed_iam

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_creates_full_catalog(db_session: AsyncSession) -> None:
    await seed_iam(db_session)
    await db_session.flush()
    scopes = set((await db_session.execute(select(Scope.name))).scalars())
    roles = set((await db_session.execute(select(Role.name))).scalars())
    assert scopes == set(SCOPES)
    assert roles == set(ROLES)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_role_carries_every_scope(db_session: AsyncSession) -> None:
    await seed_iam(db_session)
    await db_session.flush()
    admin = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    granted = set(
        (
            await db_session.execute(
                select(RoleScope.scope_name).where(RoleScope.role_id == admin.id)
            )
        ).scalars()
    )
    assert granted == set(SCOPES)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reader_role_carries_only_venue_read(db_session: AsyncSession) -> None:
    await seed_iam(db_session)
    await db_session.flush()
    reader = (await db_session.execute(select(Role).where(Role.name == "reader"))).scalar_one()
    granted = set(
        (
            await db_session.execute(
                select(RoleScope.scope_name).where(RoleScope.role_id == reader.id)
            )
        ).scalars()
    )
    assert granted == {"venue:read"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    await seed_iam(db_session)
    await db_session.flush()
    first = (await db_session.execute(select(func.count(RoleScope.role_id)))).scalar_one()
    await seed_iam(db_session)
    await db_session.flush()
    second = (await db_session.execute(select(func.count(RoleScope.role_id)))).scalar_one()
    assert first == second
