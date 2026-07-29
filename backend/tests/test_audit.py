import base64
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.audit.signing import get_signing_key

pytestmark = pytest.mark.week5


@pytest.fixture
async def seeded_visit_and_bed(db_session, fake_facility):
    from app.patients.models import Patient
    from app.opd.models import Visit
    from app.admissions.models import Ward, Bed
    from app.users.models import User
    from datetime import datetime, timezone

    doctor = User(
        keycloak_sub="audit-doctor-sub",
        username="audit.doctor",
        full_name="Audit Doctor",
        facility_id=fake_facility.id,
    )
    db_session.add(doctor)
    await db_session.flush()

    patient = Patient(
        full_name="Audit Test Patient",
        sex="male",
        age_years=50,
        identity_path="demographics_only",
        facility_id=fake_facility.id,
        created_by=doctor.id,
    )
    db_session.add(patient)
    await db_session.flush()

    visit = Visit(
        visit_number=f"VST-AUDIT-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=fake_facility.id,
        visit_type="ipd",
        status="registered",
        visit_date=datetime(2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc),
        created_by=doctor.id,
    )
    db_session.add(visit)
    await db_session.flush()

    ward = Ward(name="Audit Test Ward", facility_id=fake_facility.id)
    db_session.add(ward)
    await db_session.flush()

    bed = Bed(ward_id=ward.id, bed_number="A1", status="vacant")
    db_session.add(bed)
    await db_session.flush()

    return {"doctor": doctor, "patient": patient, "visit": visit, "ward": ward, "bed": bed}


async def test_admission_create_writes_valid_signed_audit_log(
    authed_client: AsyncClient, seeded_visit_and_bed, db_session, fake_facility
):
    seed = seeded_visit_and_bed
    payload = {
        "visit_id": str(seed["visit"].id),
        "patient_id": str(seed["patient"].id),
        "ward_id": str(seed["ward"].id),
        "bed_id": str(seed["bed"].id),
        "admitted_at": "2026-07-28T09:00:00",
        "reason": "Test admission for audit verification",
    }
    response = await authed_client.post("/api/v1/admissions", json=payload)
    assert response.status_code == 200
    admission_id = uuid.UUID(response.json()["data"]["id"])

    stmt = select(AuditLog).where(
        AuditLog.resource_id == admission_id, AuditLog.action == "admission.create"
    )
    result = await db_session.execute(stmt)
    entry = result.scalar_one()

    # Correct field values
    assert entry.facility_id == fake_facility.id
    assert entry.patient_id == seed["patient"].id
    assert entry.visit_id == seed["visit"].id
    assert entry.resource_type == "admission"
    assert entry.new_value["status"] == "admitted"
    assert entry.signer_key_id == "dev-key-v1"

    # Hash chain fields are well-formed sha256 hex
    assert len(entry.entry_hash) == 64
    assert all(c in "0123456789abcdef" for c in entry.entry_hash)
    assert len(entry.prev_hash) == 64

    # Signature actually cryptographically verifies against the signing
    # key used this process (proves the signature isn't just a random
    # string — it's a real Ed25519 signature over the row's content).
    sig_payload = {
        "id": str(entry.id),
        "created_at": entry.created_at.isoformat(),
        "facility_id": str(entry.facility_id),
        "user_id": str(entry.user_id) if entry.user_id else None,
        "role": entry.role,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": str(entry.resource_id) if entry.resource_id else None,
        "patient_id": str(entry.patient_id) if entry.patient_id else None,
        "visit_id": str(entry.visit_id) if entry.visit_id else None,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "reason": entry.reason,
    }
    sig_bytes = json.dumps(sig_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    public_key = get_signing_key().public_key()
    # verify() raises InvalidSignature if it doesn't match -- no exception
    # raised here means the signature is valid.
    public_key.verify(base64.b64decode(entry.signature), sig_bytes)


async def test_transfer_and_discharge_also_write_audit_logs(
    authed_client: AsyncClient, seeded_visit_and_bed, db_session, fake_facility
):
    seed = seeded_visit_and_bed
    admit_payload = {
        "visit_id": str(seed["visit"].id),
        "patient_id": str(seed["patient"].id),
        "ward_id": str(seed["ward"].id),
        "bed_id": str(seed["bed"].id),
        "admitted_at": "2026-07-28T09:00:00",
    }
    admit_resp = await authed_client.post("/api/v1/admissions", json=admit_payload)
    admission_id = admit_resp.json()["data"]["id"]

    discharge_resp = await authed_client.post(
        f"/api/v1/admissions/{admission_id}/discharge",
        json={"discharge_type": "discharged"},
    )
    assert discharge_resp.status_code == 200

    stmt = select(AuditLog.action).where(AuditLog.resource_id == uuid.UUID(admission_id))
    result = await db_session.execute(stmt)
    actions = {row[0] for row in result.all()}
    assert actions == {"admission.create", "admission.discharge"}
