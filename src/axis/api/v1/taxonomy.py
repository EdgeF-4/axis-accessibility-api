"""Taxonomy read endpoint — returns the controlled vocabulary by version."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from axis.api.v1.deps import DBSession
from axis.api.v1.schemas import TaxonomyAttributeOut, TaxonomyCategoryOut, TaxonomyOut
from axis.db.models import TaxonomyAttribute, TaxonomyCategory, TaxonomyVersion

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("", response_model=TaxonomyOut)
async def get_taxonomy(
    session: DBSession,
    version: Annotated[str | None, Query(description="semver; default = latest published")] = None,
) -> TaxonomyOut:
    """Return the (versioned) taxonomy. Public-read by design."""
    if version is None:
        stmt = select(TaxonomyVersion).order_by(TaxonomyVersion.published_at.desc()).limit(1)
    else:
        stmt = select(TaxonomyVersion).where(TaxonomyVersion.semver == version)
    tv = (await session.execute(stmt)).scalar_one_or_none()
    if tv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="taxonomy version not found"
        )

    cat_stmt = (
        select(TaxonomyCategory)
        .where(TaxonomyCategory.version_id == tv.id)
        .order_by(TaxonomyCategory.key)
    )
    categories = list((await session.execute(cat_stmt)).scalars().all())

    attr_stmt = (
        select(TaxonomyAttribute)
        .where(TaxonomyAttribute.version_id == tv.id)
        .order_by(TaxonomyAttribute.category_id, TaxonomyAttribute.key)
    )
    attrs = list((await session.execute(attr_stmt)).scalars().all())
    attrs_by_cat: dict[str, list[TaxonomyAttribute]] = {}
    for a in attrs:
        attrs_by_cat.setdefault(str(a.category_id), []).append(a)

    return TaxonomyOut(
        version=tv.semver,
        label=tv.label,
        published_at=tv.published_at,
        categories=[
            TaxonomyCategoryOut(
                id=c.id,
                key=c.key,
                label=c.label,
                description=c.description,
                attributes=[
                    TaxonomyAttributeOut.model_validate(a, from_attributes=True)
                    for a in attrs_by_cat.get(str(c.id), [])
                ],
            )
            for c in categories
        ],
    )


# Imports kept at end to satisfy ruff TC rules without losing runtime types.
_ = selectinload  # silence unused-import on the helper we may need later
