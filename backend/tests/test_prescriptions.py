"""Tests for app/orders/prescription_routers.py (#182, B3-W3-03)."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week3


@pytest.fixture
async def seeded_encounter_for_rx(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.users.models import User

    doctor = User(
        keycloak_sub="rx-doctor-sub",
        username="rx.doctor",
        full_name="Prescription Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Prescription Test Patient",
        sex="male",
        age_years=60,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-RX-{uuid.uuid4().hex[:8]}",
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

    return {"doctor": doctor, "patient": patient, "encounter": encounter}


async def test_create_prescription_with_items_succeeds(
    authed_client: AsyncClient, seeded_encounter_for_rx
):
    seed = seeded_encounter_for_rx
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "notes": "Take after meals",
        "items": [
            {
                "medicine_name": "Amoxicillin",
                "dosage": "500mg",
                "frequency": "TID",
                "duration_days": 7,
                "route": "oral",
                "instructions": "Complete full course",
            },
            {
                "medicine_name": "Paracetamol",
                "dosage": "650mg",
                "frequency": "SOS",
                "duration_days": 3,
            },
        ],
    }
    response = await authed_client.post("/api/v1/prescriptions", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["notes"] == "Take after meals"
    assert len(body["items"]) == 2
    names = {item["medicine_name"] for item in body["items"]}
    assert names == {"Amoxicillin", "Paracetamol"}
    assert all(item["status"] == "prescribed" for item in body["items"])


async def test_get_prescription_includes_items(
    authed_client: AsyncClient, seeded_encounter_for_rx
):
    seed = seeded_encounter_for_rx
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "items": [{"medicine_name": "Ibuprofen", "dosage": "400mg"}],
    }
    create_resp = await authed_client.post("/api/v1/prescriptions", json=payload)
    prescription_id = create_resp.json()["data"]["id"]

    response = await authed_client.get(f"/api/v1/prescriptions/{prescription_id}")
    assert response.status_code == 200
    body = response.json()["data"]
    assert len(body["items"]) == 1
    assert body["items"][0]["medicine_name"] == "Ibuprofen"


async def test_get_prescription_not_found_returns_404(authed_client: AsyncClient):
    response = await authed_client.get(f"/api/v1/prescriptions/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_prescriptions_filters_by_patient(
    authed_client: AsyncClient, seeded_encounter_for_rx
):
    seed = seeded_encounter_for_rx
    payload = {
        "encounter_id": str(seed["encounter"].id),
        "patient_id": str(seed["patient"].id),
        "created_by": str(seed["doctor"].id),
        "items": [{"medicine_name": "Cetirizine"}],
    }
    await authed_client.post("/api/v1/prescriptions", json=payload)

    response = await authed_client.get(
        "/api/v1/prescriptions", params={"patient_id": str(seed["patient"].id)}
    )
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert all(item["patient_id"] == str(seed["patient"].id) for item in items)
