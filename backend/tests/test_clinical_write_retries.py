"""Receipt replay, authorization and rollback for the eight new clinical writers."""
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event, func, select

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.blood_bank.models import BloodCrossmatch, BloodDonor, BloodUnit
from app.blood_bank.router import router as blood_router
from app.blood_bank.schemas import BloodCrossmatchCreate, BloodDonorCreate, BloodUnitCreate
from app.blood_bank.service import create_crossmatch, create_donor, create_unit
from app.common.db import get_db
from app.common.idempotency_models import IdempotencyKey
from app.forms.models import FormDefinition, FormSubmission
from app.forms.router import router as forms_router
from app.forms.schemas import FormDefinitionCreate
from app.forms.service import create_form_definition
from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.immunization.router import router as immunization_router
from app.immunization.service import ensure_catalogue_seeded
from app.users.models import User
from tests.test_suite_8_immunization_blood_forms import _setup_suite_8_fixture

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def writes(db):
    facility, staff, patient, other = await _setup_suite_8_fixture(db)
    definition = await create_form_definition(db, FormDefinitionCreate(
        code="RETRY_FORM", title="Synthetic retry form", fields_schema=[
            {"id": "observation", "label": "Observation", "type": "text", "required": True}],
    ), staff.id)
    await ensure_catalogue_seeded(db)
    donor = await create_donor(db, BloodDonorCreate(full_name="Synthetic donor", sex="male",
        blood_group="O+", weight_kg=60, hemoglobin_g_dl=14), staff.id)
    unit = await create_unit(db, BloodUnitCreate(donor_id=donor.id, bag_number="TEST-BASE",
        blood_group="O+", expiry_date=date.today() + timedelta(days=10), screening_status="passed"), staff.id)
    crossmatch = await create_crossmatch(db, BloodCrossmatchCreate(unit_id=unit.id,
        patient_id=patient.id, compatibility_result="compatible"), staff.id)
    await db.commit()
    caller = DbUser(id=staff.id, keycloak_sub=staff.keycloak_sub, username=staff.username,
                    facility_id=facility.id, roles=["admin", "doctor", "nurse", "lab_tech"])
    actor = {"current": caller}
    app = FastAPI()
    for router in (forms_router, blood_router, immunization_router):
        app.include_router(router)
    async def session():
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=actor["current"].keycloak_sub, roles=actor["current"].roles)
    app.dependency_overrides[get_current_db_user] = lambda: actor["current"]
    payloads = {
        "forms/definitions": ({"code": "NEW_RETRY", "title": "New form", "fields_schema": [
            {"id": "answer", "label": "Answer", "type": "text"}]}, FormDefinition, "title", "Changed title"),
        "forms/submissions": ({"patient_id": str(patient.id), "form_id": str(definition.id),
            "form_data": {"observation": "Synthetic test"}}, FormSubmission, "form_data", {"observation": "Changed"}),
        "immunization/records": ({"patient_id": str(patient.id), "vaccine_code": "BCG",
            "batch_number": "TEST-BATCH", "expiry_date": "2099-01-01"}, ImmunizationRecord, "batch_number", "CHANGED"),
        "blood-bank/donors": ({"full_name": "Synthetic new donor", "sex": "male", "blood_group": "O+",
            "weight_kg": 60, "hemoglobin_g_dl": 14}, BloodDonor, "full_name", "Changed donor"),
        "blood-bank/units": ({"donor_id": str(donor.id), "bag_number": "NEW-BAG", "blood_group": "O+",
            "expiry_date": "2099-01-01"}, BloodUnit, "bag_number", "CHANGED"),
        "blood-bank/crossmatch": ({"patient_id": str(patient.id), "unit_id": str(unit.id),
            "compatibility_result": "compatible"}, BloodCrossmatch, "notes", "Changed"),
        "blood-bank/issue": ({"crossmatch_id": str(crossmatch.id), "notes": "Synthetic issue"},
            BloodCrossmatch, "notes", "Changed issue"),
        "admin/csv/import": ({"entity_type": "vaccines", "csv_content":
            "code,name,target_disease,standard_doses,min_age_days,route,site,dose_quantity\n"
            "RETRY_VAX,Synthetic vaccine,Synthetic,1,0,oral,oral,test dose\n"},
            VaccineCatalogue, "csv_content", "code,name\nCHANGED,Changed\n"),
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield {"client": client, "payloads": payloads, "actor": actor, "staff": staff,
               "patient": patient, "facility": facility, "unit": unit}


ENDPOINTS = ["forms/definitions", "forms/submissions", "immunization/records", "blood-bank/donors",
             "blood-bank/units", "blood-bank/crossmatch", "blood-bank/issue", "admin/csv/import"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_lost_response_retry_returns_original_without_second_write(db, writes, endpoint):
    payload, model, field, replacement = writes["payloads"][endpoint]
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = await writes["client"].post("/" + endpoint, json=payload, headers=key)
    assert first.status_code in (200, 201), first.text
    count = await db.scalar(select(func.count()).select_from(model))
    # JSON property order must not alter action identity.
    replay = await writes["client"].post("/" + endpoint, json=dict(reversed(list(payload.items()))), headers=key)
    assert replay.status_code == first.status_code
    assert replay.json() == first.json()
    assert await db.scalar(select(func.count()).select_from(model)) == count
    changed = await writes["client"].post("/" + endpoint, json={**payload, field: replacement}, headers=key)
    assert changed.status_code == 409, changed.text
    assert changed.json()["detail"]["code"] == "idempotency_key_reuse"
    assert await db.scalar(select(func.count()).select_from(model)) == count


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_new_clinical_writes_require_a_bounded_request_key(writes, endpoint):
    payload = writes["payloads"][endpoint][0]
    for headers in ({}, {"Idempotency-Key": "x" * 201}, {"Idempotency-Key": "bad key"}):
        response = await writes["client"].post("/" + endpoint, json=payload, headers=headers)
        assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_receipt_failure_rolls_back_the_clinical_write(db, writes, endpoint):
    payload, model, _, _ = writes["payloads"][endpoint]
    count = await db.scalar(select(func.count()).select_from(model))
    key = str(uuid.uuid4())
    def fail_receipt(mapper, connection, target):
        if target.key == key and target.response_status is not None:
            raise RuntimeError("Synthetic receipt persistence failure")
    event.listen(IdempotencyKey, "before_update", fail_receipt)
    try:
        with pytest.raises(RuntimeError, match="Synthetic receipt"):
            await writes["client"].post("/" + endpoint, json=payload, headers={"Idempotency-Key": key})
    finally:
        event.remove(IdempotencyKey, "before_update", fail_receipt)
    assert await db.scalar(select(func.count()).select_from(model)) == count
    assert await db.scalar(select(func.count()).select_from(IdempotencyKey).where(IdempotencyKey.key == key)) == 0
    if endpoint == "blood-bank/issue":
        unit = await db.get(BloodUnit, writes["unit"].id)
        assert unit.status == "available"
    retry = await writes["client"].post("/" + endpoint, json=payload, headers={"Idempotency-Key": key})
    assert retry.status_code in (200, 201), retry.text


async def test_replay_rechecks_patient_scope_and_active_actor(db, writes):
    endpoint = "forms/submissions"
    payload = writes["payloads"][endpoint][0]
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    client = writes["client"]
    assert (await client.post("/" + endpoint, json=payload, headers=headers)).status_code == 201
    writes["patient"].deleted_at = datetime.now(UTC)
    await db.commit()
    assert (await client.post("/" + endpoint, json=payload, headers=headers)).status_code == 404
    writes["patient"].deleted_at = None
    writes["staff"].is_active = False
    await db.commit()
    assert (await client.post("/" + endpoint, json=payload, headers=headers)).status_code == 403


async def test_staff_facility_change_cannot_replay_a_form_definition(db, writes):
    endpoint = "forms/definitions"
    payload = writes["payloads"][endpoint][0]
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    assert (await writes["client"].post("/" + endpoint, json=payload, headers=headers)).status_code == 201
    other, _, _, _ = await _setup_suite_8_fixture(db)
    writes["staff"].facility_id = other.id
    await db.commit()
    writes["actor"]["current"] = writes["actor"]["current"].model_copy(update={"facility_id": other.id})
    response = await writes["client"].post("/" + endpoint, json=payload, headers=headers)
    assert response.status_code == 409


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_patient_role_cannot_replay_a_staff_receipt(writes, endpoint):
    payload = writes["payloads"][endpoint][0]
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    client = writes["client"]
    assert (await client.post("/" + endpoint, json=payload, headers=headers)).status_code in (200, 201)
    actor = writes["actor"]["current"]
    writes["actor"]["current"] = actor.model_copy(update={"roles": [*actor.roles, "patient"]})
    # Patient-scoped handlers conceal a missing self binding before reaching
    # the staff-only receipt guard; neither path may return the cached record.
    expected = 404 if endpoint in {"forms/submissions", "immunization/records", "blood-bank/crossmatch", "blood-bank/issue"} else 403
    assert (await client.post("/" + endpoint, json=payload, headers=headers)).status_code == expected


async def test_same_key_cannot_return_another_staff_members_receipt(db, writes):
    payload = writes["payloads"]["forms/submissions"][0]
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    client = writes["client"]
    first = await client.post("/forms/submissions", json=payload, headers=headers)
    assert first.status_code == 201
    second_staff = User(id=uuid.uuid4(), facility_id=writes["facility"].id,
        keycloak_sub=str(uuid.uuid4()), username="second-retry-staff", full_name="Synthetic second staff", is_active=True)
    db.add(second_staff)
    await db.commit()
    writes["actor"]["current"] = DbUser(id=second_staff.id, keycloak_sub=second_staff.keycloak_sub,
        username=second_staff.username, facility_id=second_staff.facility_id, roles=["admin"])
    second = await client.post("/forms/submissions", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["submitted_by"] == str(second_staff.id)


async def test_database_constraint_refusal_is_explicit_and_not_a_partial_write(db, writes):
    payload = writes["payloads"]["blood-bank/units"][0]
    client = writes["client"]
    assert (await client.post("/blood-bank/units", json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())})).status_code == 201
    key = str(uuid.uuid4())
    duplicate = await client.post("/blood-bank/units", json=payload, headers={"Idempotency-Key": key})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "clinical_write_rejected"
    assert await db.scalar(select(func.count()).select_from(IdempotencyKey).where(IdempotencyKey.key == key)) == 0
    assert await db.scalar(select(func.count()).select_from(BloodUnit).where(BloodUnit.bag_number == payload["bag_number"])) == 1
