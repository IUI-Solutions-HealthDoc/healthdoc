import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from app.opd.models import Vitals


pytestmark = pytest.mark.week5


@pytest.fixture
async def seeded_encounter_and_admission(db_session, fake_facility):
    """Minimal patients/visits/encounters/wards/beds/admissions chain so
    vitals can attach to a real encounter_id and admission_id."""
    from app.patients.models import Patient
    from app.opd.models import Visit, Encounter
    from app.admissions.models import Ward, Bed, Admission
    from app.users.models import User

    doctor = User(
        keycloak_sub="doctor-sub",
        username="doctor.user",
        full_name="Doctor User",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Test Patient",
        sex="female",
        age_years=30,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-TEST-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="opd",
        status="registered",
        visit_date=datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc),
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

    ward = Ward(name="Test Ward", facility_id=fake_facility.id)
    db_session.add(ward)
    await db_session.flush()

    bed = Bed(ward_id=ward.id, bed_number="B1", status="occupied")
    db_session.add(bed)
    await db_session.flush()

    admission = Admission(
        visit_id=visit.id,
        patient_id=patient.id,
        ward_id=ward.id,
        bed_id=bed.id,
        admitted_at=datetime(2026, 7, 28, 9, 0, 0),
        status="admitted",
        created_by=doctor.id,
    )
    db_session.add(admission)
    await db_session.flush()

    return {"patient": patient, "encounter": encounter, "admission": admission}


async def test_create_vitals_with_encounter_succeeds(authed_client: AsyncClient, seeded_encounter_and_admission):
    patient = seeded_encounter_and_admission["patient"]
    encounter = seeded_encounter_and_admission["encounter"]

    payload = {
        "patient_id": str(patient.id),
        "temp_c": "37.0",
        "pulse_bpm": 80,
        "bp_systolic": 120,
        "bp_diastolic": 80,
        "spo2_pct": 98,
    }
    response = await authed_client.post(f"/api/v1/encounters/{encounter.id}/vitals", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["encounter_id"] == str(encounter.id)
    assert body["patient_id"] == str(patient.id)
    assert body["pulse_bpm"] == 80


async def test_create_vitals_computes_bmi(authed_client: AsyncClient, seeded_encounter_and_admission):
    patient = seeded_encounter_and_admission["patient"]
    encounter = seeded_encounter_and_admission["encounter"]

    payload = {
        "patient_id": str(patient.id),
        "height_cm": "170",
        "weight_kg": "70",
    }
    response = await authed_client.post(f"/api/v1/encounters/{encounter.id}/vitals", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    # bmi = 70 / (1.70^2) ~= 24.2 -- app-computed, must not be client-suppliable
    assert body["bmi"] is not None
    assert 24.0 <= float(body["bmi"]) <= 24.3


async def test_client_supplied_bmi_is_ignored(authed_client: AsyncClient, seeded_encounter_and_admission):
    """VitalsCreate has no bmi field at all -- extra keys are simply dropped
    by Pydantic, confirming the client cannot set it directly."""
    patient = seeded_encounter_and_admission["patient"]
    encounter = seeded_encounter_and_admission["encounter"]

    payload = {
        "patient_id": str(patient.id),
        "bmi": "999.9",  # attacker-supplied, should be ignored entirely
    }
    response = await authed_client.post(f"/api/v1/encounters/{encounter.id}/vitals", json=payload)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["bmi"] != 999.9


async def test_list_vitals_for_encounter(authed_client: AsyncClient, seeded_encounter_and_admission):
    patient = seeded_encounter_and_admission["patient"]
    encounter = seeded_encounter_and_admission["encounter"]

    payload = {"patient_id": str(patient.id), "pulse_bpm": 72}
    await authed_client.post(f"/api/v1/encounters/{encounter.id}/vitals", json=payload)

    response = await authed_client.get(f"/api/v1/encounters/{encounter.id}/vitals")
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) >= 1
    assert items[0]["encounter_id"] == str(encounter.id)
