"""Registration and search defects from the 10-12 October 2026 QA reports.

- A duplicate ABHA number answered 500 instead of naming the patient.
- The same person could be registered twice with no warning.
- A 3-year-old could be registered without a guardian.
- Guardian names accepted digits and markup.
- "Test Patient Oct" matched "Dev Patient" on name + DOB.
- Search had no age option, though registration does.
"""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.patients import router as patients_router
from app.patients.models import Patient
from app.patients.schemas import PatientCreate, PatientSearchRequest, PatientUpdate
from app.patients.service import find_probable_duplicates, search_patients
from app.users.models import Facility, User
from tests.pg_fixtures import db, engine  # noqa: F401  (trigram search needs real PostgreSQL)

pytestmark = pytest.mark.asyncio


async def _facility(db) -> Facility:
    facility = Facility(id=uuid.uuid4(), name="QA DH", code=f"Q{uuid.uuid4().hex[:5].upper()}",
                        state_code="DL", timezone="Asia/Kolkata")
    db.add(facility)
    await db.flush()
    return facility


async def _staff(db, facility_id) -> User:
    user = User(id=uuid.uuid4(), facility_id=facility_id, keycloak_sub=f"sub-{uuid.uuid4().hex[:8]}",
                username=f"u-{uuid.uuid4().hex[:8]}", full_name="Desk", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _patient(db, facility, staff, **extra) -> Patient:
    fields = {
        "id": uuid.uuid4(), "facility_id": facility.id, "uhid": f"UHID-{uuid.uuid4().hex[:8]}",
        "full_name": "Ram Kumar", "sex": "male", "age_years": 36, "dob": date(1990, 1, 15),
        "mobile": "+919876543210", "status": "active", "identity_path": "demographics_only",
        "created_by": staff.id,
    }
    patient = Patient(**{**fields, **extra})
    db.add(patient)
    await db.flush()
    return patient


def _adult(**extra) -> dict:
    return {"full_name": "Ram Kumar", "sex": "male", "dob": "1990-01-15", "mobile": "9876543210", **extra}


# ------------------------------------------------------------------ schema


def test_a_minor_needs_a_guardian():
    with pytest.raises(ValidationError, match="under 18"):
        PatientCreate(full_name="Child", sex="female", age_years=3)
    ok = PatientCreate(full_name="Child", sex="female", age_years=3,
                       guardian_name="Sita Devi", guardian_relationship="mother")
    assert ok.guardian_name == "Sita Devi"


def test_a_minor_by_date_of_birth_needs_a_guardian_too():
    with pytest.raises(ValidationError, match="under 18"):
        PatientCreate(full_name="Child", sex="male", dob=date.today().replace(year=date.today().year - 3))


def test_an_adult_needs_no_guardian():
    assert PatientCreate(**_adult()).guardian_name is None


@pytest.mark.parametrize("bad", ["12345 <script>", "Ram7", "a@b"])
def test_a_guardian_name_follows_the_name_rule(bad):
    with pytest.raises(ValidationError, match="guardian_name"):
        PatientCreate(**_adult(guardian_name=bad, guardian_relationship="father"))
    with pytest.raises(ValidationError, match="guardian_name"):
        PatientUpdate(guardian_name=bad)


def test_a_guardian_name_needs_a_relationship():
    with pytest.raises(ValidationError, match="guardian_relationship"):
        PatientCreate(**_adult(guardian_name="Sita Devi"))


def test_search_by_name_and_age():
    request = PatientSearchRequest(full_name="Ram Kumar", age_years=45)
    assert request.age_years == 45
    with pytest.raises(ValidationError):
        PatientSearchRequest(full_name="Ram Kumar", age_years=45, dob="1990-01-15")


# ------------------------------------------------------------------ search


async def test_a_shared_word_is_not_a_name_match(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    await _patient(db, facility, staff, full_name="Dev Patient", dob=date(1990, 1, 1), mobile=None)
    results, _ = await search_patients(db, facility_id=facility.id, full_name="Test Patient Oct",
                                       dob=date(1990, 1, 1))
    assert results == []


async def test_a_close_spelling_still_matches(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    target = await _patient(db, facility, staff, full_name="Ramesh Kumar", mobile=None)
    results, _ = await search_patients(db, facility_id=facility.id, full_name="Ramesh Kumaar",
                                       dob=date(1990, 1, 15))
    assert [r[0].id for r in results] == [target.id]


async def test_search_by_age_finds_age_and_dob_registrations(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    by_age = await _patient(db, facility, staff, full_name="Ram Kumar", dob=None, age_years=45, mobile=None)
    by_dob = await _patient(db, facility, staff, full_name="Ram Kumar",
                            dob=date(date.today().year - 44, 6, 1), mobile=None)
    far = await _patient(db, facility, staff, full_name="Ram Kumar", dob=None, age_years=70, mobile=None)
    results, _ = await search_patients(db, facility_id=facility.id, full_name="Ram Kumar", age_years=45)
    found = {r[0].id for r in results}
    assert {by_age.id, by_dob.id} <= found and far.id not in found
    assert {r[2] for r in results} == {"name_age"}


async def test_every_matched_criterion_is_reported(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    await _patient(db, facility, staff)
    results, _ = await search_patients(db, facility_id=facility.id, full_name="Ram Kumar",
                                       dob=date(1990, 1, 15), mobile="+919876543210")
    assert len(results) == 1
    assert results[0][2] == "mobile" and results[0][4] == ["mobile", "name_dob"]


# ------------------------------------------------------------------ duplicates


async def test_the_same_name_dob_and_mobile_is_a_probable_duplicate(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    existing = await _patient(db, facility, staff)
    found = await find_probable_duplicates(db, facility_id=facility.id, full_name="ram  KUMAR",
                                           mobile="+919876543210", dob=date(1990, 1, 15))
    assert [p.id for p in found] == [existing.id]


async def test_a_family_sharing_a_phone_is_not_a_duplicate(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    await _patient(db, facility, staff)
    assert await find_probable_duplicates(db, facility_id=facility.id, full_name="Sita Kumari",
                                          mobile="+919876543210", dob=date(1992, 3, 3)) == []
    assert await find_probable_duplicates(db, facility_id=facility.id, full_name="Ram Kumar",
                                          mobile="+919876543210", dob=date(2015, 3, 3)) == []


async def _register(db, facility, staff, **body):
    user = SimpleNamespace(id=staff.id, facility_id=facility.id)
    return await patients_router.register_patient(
        PatientCreate(**body), current_db_user=user, db=db, idempotency_key=str(uuid.uuid4()),
    )


async def test_registering_the_same_person_twice_asks_first(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    existing = await _patient(db, facility, staff)
    with pytest.raises(HTTPException) as refused:
        await _register(db, facility, staff, **_adult())
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "possible_duplicate"
    assert [c["patient_id"] for c in refused.value.detail["candidates"]] == [str(existing.id)]
    created = await _register(db, facility, staff, **_adult(confirm_not_duplicate=True))
    assert created["id"] != str(existing.id) if isinstance(created, dict) else created.id != existing.id


async def test_a_duplicate_abha_names_the_patient_instead_of_500(db):
    facility = await _facility(db)
    staff = await _staff(db, facility.id)
    holder = await _patient(db, facility, staff, abha_number="12345678901234", mobile=None)
    with pytest.raises(HTTPException) as refused:
        await _register(db, facility, staff, full_name="Other Person", sex="female",
                        dob="1985-05-05", abha_number="12345678901234")
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "duplicate_abha"
    assert refused.value.detail["candidate_uhid"] == holder.uhid
