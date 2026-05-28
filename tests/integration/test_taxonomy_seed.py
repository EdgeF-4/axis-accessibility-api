"""Taxonomy seed — must be idempotent (safe to run any number of times)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from axis.db.models import TaxonomyAttribute, TaxonomyCategory, TaxonomyVersion
from axis.db.seed import seed_taxonomy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    version1 = await seed_taxonomy(db_session)
    await db_session.flush()
    count_after_first = (
        await db_session.execute(select(func.count(TaxonomyAttribute.id)))
    ).scalar_one()

    version2 = await seed_taxonomy(db_session)
    await db_session.flush()
    count_after_second = (
        await db_session.execute(select(func.count(TaxonomyAttribute.id)))
    ).scalar_one()

    assert version1.id == version2.id
    assert count_after_first == count_after_second
    assert count_after_first > 30  # Sanity: the v1 vocabulary has ~37 attributes.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_creates_five_categories(db_session: AsyncSession) -> None:
    await seed_taxonomy(db_session)
    await db_session.flush()
    categories = (await db_session.execute(select(TaxonomyCategory.key))).scalars().all()
    assert set(categories) == {"mobility", "vision", "hearing", "cognitive", "sensory"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_version_is_one_oh(db_session: AsyncSession) -> None:
    version = await seed_taxonomy(db_session)
    await db_session.flush()
    fetched = (
        await db_session.execute(select(TaxonomyVersion).where(TaxonomyVersion.id == version.id))
    ).scalar_one()
    assert fetched.semver == "1.0.0"
