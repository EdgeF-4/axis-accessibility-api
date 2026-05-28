"""Model-level integration tests against a live Postgres.

Every invariant we declared in CHECK / partial-unique form must actually
reject the violating insert. These are the tests that catch a missing
migration step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from axis.db.models import (
    Datapoint,
    Provenance,
    TaxonomyAttribute,
    TaxonomyCategory,
    TaxonomyVersion,
    Venue,
)
from axis.db.models.enums import ValueType
from axis.ids import new_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_taxonomy(session: AsyncSession) -> TaxonomyAttribute:
    version = TaxonomyVersion(semver="test-1.0.0", label="test")
    session.add(version)
    await session.flush()
    category = TaxonomyCategory(key="mobility", label="Mobility", version_id=version.id)
    session.add(category)
    await session.flush()
    attr = TaxonomyAttribute(
        key="step_free_entrance",
        label="Step-free entrance",
        value_type=ValueType.BOOL,
        category_id=category.id,
        version_id=version.id,
    )
    session.add(attr)
    await session.flush()
    return attr


async def _make_venue(session: AsyncSession, name: str = "Hotel Test") -> Venue:
    venue = Venue(name=name, venue_type="hotel", country_code="DE")
    session.add(venue)
    await session.flush()
    return venue


@pytest.mark.integration
@pytest.mark.asyncio
async def test_datapoint_inserts_and_round_trips(db_session: AsyncSession) -> None:
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    dp = Datapoint(
        venue_id=venue.id,
        attribute_id=attr.id,
        value_bool=True,
        confidence=0.95,
        provenance=Provenance.HUMAN,
    )
    db_session.add(dp)
    await db_session.flush()

    fetched = (
        await db_session.execute(select(Datapoint).where(Datapoint.id == dp.id))
    ).scalar_one()
    assert fetched.value_bool is True
    assert fetched.provenance is Provenance.HUMAN
    assert float(fetched.confidence) == pytest.approx(0.95)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_confidence_check_rejects_out_of_range(db_session: AsyncSession) -> None:
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    db_session.add(
        Datapoint(
            venue_id=venue.id,
            attribute_id=attr.id,
            value_bool=True,
            confidence=1.5,
            provenance=Provenance.HUMAN,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_value_exactly_one_check_rejects_no_value(db_session: AsyncSession) -> None:
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    db_session.add(
        Datapoint(
            venue_id=venue.id,
            attribute_id=attr.id,
            confidence=0.9,
            provenance=Provenance.HUMAN,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_value_exactly_one_check_rejects_two_values(
    db_session: AsyncSession,
) -> None:
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    db_session.add(
        Datapoint(
            venue_id=venue.id,
            attribute_id=attr.id,
            value_bool=True,
            value_numeric=42,
            confidence=0.9,
            provenance=Provenance.HUMAN,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_fact_partial_unique_rejects_second_live(
    db_session: AsyncSession,
) -> None:
    """Two live datapoints with the same (venue, attribute, provenance) are forbidden."""
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    db_session.add(
        Datapoint(
            venue_id=venue.id,
            attribute_id=attr.id,
            value_bool=True,
            confidence=0.9,
            provenance=Provenance.HUMAN,
        )
    )
    await db_session.flush()
    db_session.add(
        Datapoint(
            venue_id=venue.id,
            attribute_id=attr.id,
            value_bool=False,
            confidence=0.9,
            provenance=Provenance.HUMAN,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_superseded_row_is_allowed_alongside_live(db_session: AsyncSession) -> None:
    """A row with superseded_by_id set is exempt from the live-fact unique."""
    attr = await _make_taxonomy(db_session)
    venue = await _make_venue(db_session)
    live = Datapoint(
        venue_id=venue.id,
        attribute_id=attr.id,
        value_bool=True,
        confidence=0.9,
        provenance=Provenance.HUMAN,
    )
    db_session.add(live)
    await db_session.flush()
    audit = Datapoint(
        id=new_id(),
        venue_id=venue.id,
        attribute_id=attr.id,
        value_bool=False,
        confidence=0.9,
        provenance=Provenance.HUMAN,
        superseded_by_id=live.id,
    )
    db_session.add(audit)
    await db_session.flush()  # MUST succeed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_country_code_regex(db_session: AsyncSession) -> None:
    db_session.add(Venue(name="Bad", venue_type="hotel", country_code="de"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_venue_search_vector_is_populated(db_session: AsyncSession) -> None:
    venue = Venue(
        name="Hotel Central",
        venue_type="hotel",
        country_code="DE",
        description="Step-free entrance and roll-in shower.",
    )
    db_session.add(venue)
    await db_session.flush()
    row = (
        await db_session.execute(
            text("SELECT search_vector::text FROM venues WHERE id = :i").bindparams(i=venue.id)
        )
    ).scalar_one()
    assert "step-free" in row.lower() or "hotel" in row.lower()
