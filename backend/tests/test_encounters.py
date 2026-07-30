"""Tests for app/encounters/router.py encounter CRUD (#180, B3-W3-01)."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week3


@pytest.fixture
async def seeded_visit(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit
    from app.users.models import User

    doctor = User(
        keycloak_sub="enc-doctor-sub",
        username="enc.doctor",
        full_name="Encounter Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Encounter Test Patient",
        sex="female",
        age_years=28,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-ENC-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="registered",
        visit_date=datetime(2026, 7, 25, 9, 0, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(visit)
    await db_session.flush()

    return {"doctor": doctor, "patient": patient, "visit": visit}


async def test_create_encounter_succeeds(authed_client: AsyncClient, seeded_visit):
    seed = seeded_visit
    payload = {
        "visit_id": str(seed["visit"].id),
        "provider_user_id": str(seed["doctor"].id),
        "created_by": str(seed["doctor"].id),
        "encounter_type": "opd",
        "chief_complaint": "Fever for 2 days",
    }
    response = await authed_client.post("/api/v1/encounters", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["visit_id"] == str(seed["visit"].id)
    assert body["chief_complaint"] == "Fever for 2 days"
    assert body["started_at"] is not None
    assert body["ended_at"] is None


async def test_get_encounter_not_found_returns_404(authed_client: AsyncClient):
    response = await authed_client.get(f"/api/v1/encounters/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_update_encounter_sets_soap_fields(authed_client: AsyncClient, seeded_visit):
    seed = seeded_visit
    create_payload = {
        "visit_id": str(seed["visit"].id),
        "provider_user_id": str(seed["doctor"].id),
        "created_by": str(seed["doctor"].id),
    }
    create_resp = await authed_client.post("/api/v1/encounters", json=create_payload)
    encounter_id = create_resp.json()["data"]["id"]

    update_payload = {
        "subjective": "Patient reports cough",
        "objective": "Chest clear",
        "assessment": "Viral URI",
        "plan": "Rest and fluids",
    }
    response = await authed_client.patch(f"/api/v1/encounters/{encounter_id}", json=update_payload)
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["subjective"] == "Patient reports cough"
    assert body["assessment"] == "Viral URI"


async def test_list_encounters_filters_by_visit(authed_client: AsyncClient, seeded_visit):
    seed = seeded_visit
    payload = {
        "visit_id": str(seed["visit"].id),
        "provider_user_id": str(seed["doctor"].id),
        "created_by": str(seed["doctor"].id),
    }
    await authed_client.post("/api/v1/encounters", json=payload)

    response = await authed_client.get("/api/v1/encounters", params={"visit_id": str(seed["visit"].id)})
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert all(item["visit_id"] == str(seed["visit"].id) for item in items)
