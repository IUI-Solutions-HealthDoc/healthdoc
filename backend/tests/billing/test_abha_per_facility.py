"""One ABHA per chart per facility (0095), enforced by PostgreSQL itself.

Real PostgreSQL (tests/billing/conftest.py), because the guarantee is the
constraint, not the application check in front of it.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.billing.conftest import seed_facility, seed_patient

pytestmark = pytest.mark.asyncio


async def _bind(db, patient_id: uuid.UUID, number: str, address: str) -> None:
    await db.execute(
        sa.text("UPDATE patients SET abha_number = :n, abha_address = :a WHERE id = :id"),
        {"n": number, "a": address, "id": patient_id},
    )
    await db.flush()


async def test_one_person_may_hold_a_linked_chart_at_each_facility(db, facility, user):
    other = await seed_facility(db)
    here = await seed_patient(db, facility_id=facility, created_by=user)
    there = await seed_patient(db, facility_id=other, created_by=user)
    await _bind(db, here, "91-0000-0000-0001", "same.person@sbx")
    await _bind(db, there, "91-0000-0000-0001", "same.person@sbx")


@pytest.mark.parametrize("column", ["abha_number", "abha_address"])
async def test_two_charts_at_one_facility_cannot_share_an_abha(db, facility, user, column):
    first = await seed_patient(db, facility_id=facility, created_by=user)
    second = await seed_patient(db, facility_id=facility, created_by=user)
    await _bind(db, first, "91-0000-0000-0002", "dup.person@sbx")
    with pytest.raises(IntegrityError, match=f"uq_patients_facility_{column}"):
        await db.execute(
            sa.text(f"UPDATE patients SET {column} = :v WHERE id = :id"),
            {"v": "91-0000-0000-0002" if column == "abha_number" else "dup.person@sbx", "id": second},
        )
        await db.flush()
