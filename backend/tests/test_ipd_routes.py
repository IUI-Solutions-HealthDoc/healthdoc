import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.week5


@pytest.fixture
async def seeded_visit_and_beds(db_session, fake_facility):
    """Minimal patient/visit/ward/beds so admission/transfer/discharge
    endpoints have valid foreign keys to work against."""
    from app.patients.models import Patient
    from app.opd.models import Visit
    from app.admissions.models import Ward, Bed
    from app.users.models import User

    doctor = User(
        keycloak_sub="ipd-doctor-sub",
        username="ipd.doctor",
        full_name="IPD Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="IPD Test Patient",
        sex="male",
        age_years=45,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-IPD-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="ipd",
        status="registered",
        visit_date=datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(visit)
    await db_session.flush()

    ward = Ward(name="IPD Test Ward", facility_id=fake_facility.id)
    db_session.add(ward)
    await db_session.flush()

    bed_a = Bed(ward_id=ward.id, bed_number="A1", status="vacant")
    bed_b = Bed(ward_id=ward.id, bed_number="A2", status="vacant")
    db_session.add_all([bed_a, bed_b])
    await db_session.flush()

    return {
        "doctor": doctor,
        "patient": patient,
        "visit": visit,
        "ward": ward,
        "bed_a": bed_a,
        "bed_b": bed_b,
    }


async def _admit(authed_client, seed, bed=None, reason="Fever"):
    payload = {
        "visit_id": str(seed["visit"].id),
        "patient_id": str(seed["patient"].id),
        "ward_id": str(seed["ward"].id),
        "bed_id": str((bed or seed["bed_a"]).id),
        "admitted_at": "2026-07-28T09:00:00",
        "reason": reason,
    }
    return await authed_client.post("/api/v1/admissions", json=payload)


async def test_create_admission_succeeds(authed_client: AsyncClient, seeded_visit_and_beds, db_session):
    seed = seeded_visit_and_beds

    response = await _admit(authed_client, seed)
    assert response.status_code == 200
    body = response.json()["data"]

    assert body["visit_id"] == str(seed["visit"].id)
    assert body["patient_id"] == str(seed["patient"].id)
    assert body["bed_id"] == str(seed["bed_a"].id)
    assert body["status"] == "admitted"

    await db_session.refresh(seed["bed_a"])
    assert seed["bed_a"].status == "occupied"


async def test_create_admission_fails_if_bed_not_vacant(authed_client: AsyncClient, seeded_visit_and_beds, db_session):
    seed = seeded_visit_and_beds
    seed["bed_a"].status = "occupied"
    db_session.add(seed["bed_a"])
    await db_session.flush()

    response = await _admit(authed_client, seed)
    assert response.status_code == 409


async def test_transfer_moves_patient_to_new_bed(authed_client: AsyncClient, seeded_visit_and_beds, db_session):
    seed = seeded_visit_and_beds
    admit_resp = await _admit(authed_client, seed)
    admission_id = admit_resp.json()["data"]["id"]

    payload = {
        "to_ward_id": str(seed["ward"].id),
        "to_bed_id": str(seed["bed_b"].id),
        "reason": "Ward transfer",
    }
    response = await authed_client.post(f"/api/v1/admissions/{admission_id}/transfer", json=payload)
    assert response.status_code == 200
    body = response.json()["data"]

    assert body["admission_id"] == admission_id
    assert body["from_bed_id"] == str(seed["bed_a"].id)
    assert body["to_bed_id"] == str(seed["bed_b"].id)

    await db_session.refresh(seed["bed_a"])
    await db_session.refresh(seed["bed_b"])
    assert seed["bed_a"].status == "vacant"
    assert seed["bed_b"].status == "occupied"


async def test_transfer_fails_if_admission_not_active(authed_client: AsyncClient, seeded_visit_and_beds):
    seed = seeded_visit_and_beds
    admit_resp = await _admit(authed_client, seed)
    admission_id = admit_resp.json()["data"]["id"]

    discharge_payload = {"discharge_type": "discharged"}
    discharge_resp = await authed_client.post(f"/api/v1/admissions/{admission_id}/discharge", json=discharge_payload)
    assert discharge_resp.status_code == 200

    transfer_payload = {
        "to_ward_id": str(seed["ward"].id),
        "to_bed_id": str(seed["bed_b"].id),
    }
    response = await authed_client.post(f"/api/v1/admissions/{admission_id}/transfer", json=transfer_payload)
    assert response.status_code == 409


async def test_transfer_fails_if_target_bed_not_vacant(authed_client: AsyncClient, seeded_visit_and_beds, db_session):
    seed = seeded_visit_and_beds
    admit_resp = await _admit(authed_client, seed)
    admission_id = admit_resp.json()["data"]["id"]

    seed["bed_b"].status = "occupied"
    db_session.add(seed["bed_b"])
    await db_session.flush()

    payload = {
        "to_ward_id": str(seed["ward"].id),
        "to_bed_id": str(seed["bed_b"].id),
    }
    response = await authed_client.post(f"/api/v1/admissions/{admission_id}/transfer", json=payload)
    assert response.status_code == 409


async def test_discharge_marks_admission_discharged_and_frees_bed(authed_client: AsyncClient, seeded_visit_and_beds, db_session):
    seed = seeded_visit_and_beds
    admit_resp = await _admit(authed_client, seed)
    admission_id = admit_resp.json()["data"]["id"]

    payload = {
        "discharge_type": "discharged",
        "discharge_summary": "Recovered well",
        "follow_up_date": "2026-08-05",
    }
    response = await authed_client.post(f"/api/v1/admissions/{admission_id}/discharge", json=payload)
    assert response.status_code == 200
    body = response.json()["data"]

    assert body["admission_id"] == admission_id
    assert body["discharge_type"] == "discharged"
    assert body["follow_up_date"] == "2026-08-05"

    from app.admissions.models import Admission
    admission = await db_session.get(Admission, uuid.UUID(admission_id))
    assert admission.status == "discharged"

    await db_session.refresh(seed["bed_a"])
    assert seed["bed_a"].status == "vacant"


async def test_discharge_fails_if_admission_not_active(authed_client: AsyncClient, seeded_visit_and_beds):
    seed = seeded_visit_and_beds
    admit_resp = await _admit(authed_client, seed)
    admission_id = admit_resp.json()["data"]["id"]

    payload = {"discharge_type": "discharged"}
    first = await authed_client.post(f"/api/v1/admissions/{admission_id}/discharge", json=payload)
    assert first.status_code == 200

    second = await authed_client.post(f"/api/v1/admissions/{admission_id}/discharge", json=payload)
    assert second.status_code == 409
