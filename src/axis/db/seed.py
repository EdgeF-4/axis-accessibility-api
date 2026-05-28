"""Idempotent taxonomy seeding.

Reads ``src/axis/seed/taxonomy_v1.json`` and upserts the version, categories,
and attributes. Safe to run any number of times; on re-run, existing rows
are left untouched (uniqueness is per-``(key, version_id)``).

Usage from a Python shell::

    import asyncio
    from axis.db.seed import seed_taxonomy_v1

    asyncio.run(seed_taxonomy_v1())
"""

from __future__ import annotations

import json
from importlib import resources
from typing import TYPE_CHECKING, Any, TypedDict, cast

from sqlalchemy import select

from axis.db.base import session_scope
from axis.db.models.enums import ValueType
from axis.db.models.taxonomy import TaxonomyAttribute, TaxonomyCategory, TaxonomyVersion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _AttrSpec(TypedDict, total=False):
    key: str
    label: str
    value_type: str
    unit: str
    description: str


class _CatSpec(TypedDict, total=False):
    key: str
    label: str
    description: str
    attributes: list[_AttrSpec]


class _TaxonomySpec(TypedDict):
    version: str
    label: str
    categories: list[_CatSpec]


def _load_spec() -> _TaxonomySpec:
    with resources.files("axis.seed").joinpath("taxonomy_v1.json").open("r", encoding="utf-8") as f:
        raw: Any = json.load(f)
    return cast("_TaxonomySpec", raw)


async def _ensure_version(session: AsyncSession, semver: str, label: str) -> TaxonomyVersion:
    existing = await session.execute(
        select(TaxonomyVersion).where(TaxonomyVersion.semver == semver)
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found
    version = TaxonomyVersion(semver=semver, label=label)
    session.add(version)
    await session.flush()
    return version


async def _ensure_category(
    session: AsyncSession,
    *,
    key: str,
    label: str,
    description: str | None,
    version_id: Any,
) -> TaxonomyCategory:
    existing = await session.execute(
        select(TaxonomyCategory).where(
            TaxonomyCategory.key == key,
            TaxonomyCategory.version_id == version_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found
    cat = TaxonomyCategory(key=key, label=label, description=description, version_id=version_id)
    session.add(cat)
    await session.flush()
    return cat


async def _ensure_attribute(
    session: AsyncSession,
    *,
    key: str,
    label: str,
    value_type: ValueType,
    unit: str | None,
    description: str | None,
    category_id: Any,
    version_id: Any,
) -> TaxonomyAttribute:
    existing = await session.execute(
        select(TaxonomyAttribute).where(
            TaxonomyAttribute.key == key,
            TaxonomyAttribute.version_id == version_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found
    attr = TaxonomyAttribute(
        key=key,
        label=label,
        value_type=value_type,
        unit=unit,
        description=description,
        category_id=category_id,
        version_id=version_id,
    )
    session.add(attr)
    await session.flush()
    return attr


async def seed_taxonomy(session: AsyncSession) -> TaxonomyVersion:
    """Apply the bundled v1 taxonomy idempotently into ``session``."""
    spec = _load_spec()
    version = await _ensure_version(session, semver=spec["version"], label=spec["label"])
    for cat in spec["categories"]:
        category = await _ensure_category(
            session,
            key=cat["key"],
            label=cat["label"],
            description=cat.get("description"),
            version_id=version.id,
        )
        for attr in cat.get("attributes", []):
            await _ensure_attribute(
                session,
                key=attr["key"],
                label=attr["label"],
                value_type=ValueType(attr["value_type"]),
                unit=attr.get("unit"),
                description=attr.get("description"),
                category_id=category.id,
                version_id=version.id,
            )
    return version


async def seed_taxonomy_v1() -> TaxonomyVersion:
    """Convenience wrapper that opens a session, seeds, and commits."""
    async with session_scope() as session:
        return await seed_taxonomy(session)
