"""Tests for app/encounters/diagnosis_routers.py (#180, B3-W3-01)."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week3


@pytest.fixture
async def seeded_encounter_for_diagnosis(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor = User(
        keycloak_sub="dx-doctor-sub",
        username="dx.doctor",
        full_name="Diagnosis Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Diagnosis Test Patient",
        sex="female",
        age_years=44,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-DX-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime(2026, 7, 25, 9, 0, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(visit)
    await db_session.flush()

    encounter = Encounter(
        visit_id=visit.id,
        provider_user_id=doctor.id,
        created_by=doctor.id,
    )
    db_session.add(encounter)
    await db_session.flush()

    return {"doctor": doctor, "encounter": encounter}


async def test_create_diagnosis_with_icd_version(
    authed_client: AsyncClient, seeded_encounter_for_diagnosis
):
    seed = seeded_encounter_for_diagnosis
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "created_by": str(seed["doctor"].id),
        "icd_code": "J06.9",
        "icd_version": "icd10",
        "diagnosis_text": "Acute upper respiratory infection, unspecified",
        "diagnosis_type": "primary",
        "is_primary": True,
    }
    response = await authed_client.post("/api/v1/diagnoses", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["icd_code"] == "J06.9"
    assert body["icd_version"] == "icd10"
    assert body["is_primary"] is True


async def test_list_diagnoses_filters_by_encounter(
    authed_client: AsyncClient, seeded_encounter_for_diagnosis
):
    seed = seeded_encounter_for_diagnosis
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "created_by": str(seed["doctor"].id),
        "icd_code": "R50.9",
        "icd_version": "icd10",
        "diagnosis_text": "Fever, unspecified",
        "diagnosis_type": "secondary",
    }
    await authed_client.post("/api/v1/diagnoses", json=payload)

    response = await authed_client.get(
        "/api/v1/diagnoses", params={"encounter_id": str(seed["encounter"].id)}
    )
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert all(item["encounter_id"] == str(seed["encounter"].id) for item in items)


async def test_icd_search_finds_seeded_codes(authed_client: AsyncClient, db_session):
    from app.opd.models import IcdCode

    db_session.add_all([
        IcdCode(version="icd10", code="J06.9", title="Acute upper respiratory infection"),
        IcdCode(version="icd10", code="A09", title="Infectious gastroenteritis"),
    ])
    await db_session.flush()

    response = await authed_client.get("/api/v1/diagnoses/icd-search", params={"q": "respiratory"})
    assert response.status_code == 200
    results = response.json()["data"]
    assert len(results) >= 1
    assert any(r["code"] == "J06.9" for r in results)
