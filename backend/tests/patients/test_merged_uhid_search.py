"""A retired UHID resolves to its surviving chart only inside the caller's facility."""
import uuid

import pytest

from app.patients.models import Patient
from app.patients.service import search_patients
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _facility(db, code: str) -> Facility:
    facility = Facility(id=uuid.uuid4(), name=f"Facility {code}", code=code, state_code="MH")
    db.add(facility)
    await db.flush()
    return facility


def _patient(facility_id, created_by, **extra) -> Patient:
    fields = {
        "id": uuid.uuid4(), "facility_id": facility_id, "uhid": f"UHID-{uuid.uuid4().hex[:8]}",
        "full_name": "Merge Test", "sex": "male", "age_years": 40, "status": "active",
        "identity_path": "demographics_only", "created_by": created_by,
    }
    return Patient(**{**fields, **extra})


async def _staff(db, facility_id) -> User:
    user = User(id=uuid.uuid4(), facility_id=facility_id, keycloak_sub=f"sub-{uuid.uuid4().hex[:8]}",
                username=f"u-{uuid.uuid4().hex[:8]}", full_name="Desk", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def test_a_merged_uhid_finds_the_surviving_chart_with_the_standard_result_shape(db):
    here = await _facility(db, f"H{uuid.uuid4().hex[:5].upper()}")
    staff = await _staff(db, here.id)
    survivor = _patient(here.id, staff.id)
    db.add(survivor)
    await db.flush()
    retired = _patient(here.id, staff.id, status="merged", merged_into_patient_id=survivor.id)
    db.add(retired)
    await db.flush()

    results, total = await search_patients(db, facility_id=here.id, uhid=retired.uhid)

    assert total == 1
    patient, score, matched_on, merged_from = results[0]
    assert patient.id == survivor.id
    assert (score, matched_on, merged_from) == (1.0, "merged_identifier", retired.uhid)


async def test_a_merge_pointing_at_another_facility_does_not_leak_that_chart(db):
    here = await _facility(db, f"H{uuid.uuid4().hex[:5].upper()}")
    elsewhere = await _facility(db, f"E{uuid.uuid4().hex[:5].upper()}")
    staff = await _staff(db, here.id)
    foreign_survivor = _patient(elsewhere.id, staff.id)
    db.add(foreign_survivor)
    await db.flush()
    retired = _patient(here.id, staff.id, status="merged", merged_into_patient_id=foreign_survivor.id)
    db.add(retired)
    await db.flush()

    results, total = await search_patients(db, facility_id=here.id, uhid=retired.uhid)

    assert (results, total) == ([], 0)


async def test_every_exact_match_path_returns_four_fields(db):
    here = await _facility(db, f"H{uuid.uuid4().hex[:5].upper()}")
    staff = await _staff(db, here.id)
    patient = _patient(here.id, staff.id, mobile="+919876543210")
    db.add(patient)
    await db.flush()

    for criteria in ({"uhid": patient.uhid}, {"mobile": "+919876543210"}):
        results, _ = await search_patients(db, facility_id=here.id, **criteria)
        assert [len(item) for item in results] == [4]
        assert results[0][3] is None
