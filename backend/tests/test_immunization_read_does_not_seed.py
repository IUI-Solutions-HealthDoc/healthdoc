"""Reading the vaccine catalogue must not write.

The first GET of an empty catalogue used to insert the defaults. Two
simultaneous first reads both saw it empty, and the second insert failed on
the unique code: a 500 from GET /immunization/catalogue on staging CI (run
36873900247). Seeding now belongs to the seed script alone, like forms and
order sets.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.immunization import router as immunization_router
from app.immunization.models import VaccineCatalogue
from app.immunization.service import DEFAULT_NATIONAL_VACCINES, ensure_catalogue_seeded

pytestmark = pytest.mark.asyncio


async def _count(db) -> int:
    return await db.scalar(select(func.count()).select_from(VaccineCatalogue))


async def test_listing_an_empty_catalogue_writes_nothing(db):
    assert await immunization_router.list_catalogue(db=db) == []
    assert await _count(db) == 0


async def test_seed_fills_only_missing_codes_and_is_repeatable(db):
    edited = dict(DEFAULT_NATIONAL_VACCINES[0], name="Locally edited")
    db.add(VaccineCatalogue(id=uuid.uuid4(), **edited))
    await db.flush()

    await ensure_catalogue_seeded(db)
    await ensure_catalogue_seeded(db)

    assert await _count(db) == len(DEFAULT_NATIONAL_VACCINES)
    kept = await db.scalar(
        select(VaccineCatalogue.name).where(VaccineCatalogue.code == edited["code"])
    )
    assert kept == "Locally edited"
