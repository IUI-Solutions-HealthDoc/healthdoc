"""Tests for bed status reconciliation. Tested directly against the
service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from app.admissions import service
from app.admissions.models import Admission, Bed, Ward
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _make_facility(db):
    facility_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    await db.flush()
    return facility_id


async def _make_ward_and_bed(db, facility_id, bed_status="vacant"):
    ward_id = uuid.uuid4()
    bed_id = uuid.uuid4()
    db.add(Ward(id=ward_id, name="Test Ward", facility_id=facility_id))
    db.add(Bed(id=bed_id, ward_id=ward_id, bed_number="B1", status=bed_status))
    await db.flush()
    return ward_id, bed_id


async def _make_patient_and_visit(db, facility_id):
    patient_id = uuid.uuid4()
    db.add(Patient(
        id=patient_id, uhid=f"UHID{uuid.uuid4().hex[:8]}", full_name="Test Patient",
        sex="male", dob=date(1990, 1, 1), facility_id=facility_id,
        identity_path="demographics_only", identity_status="verified",
        created_by=uuid.uuid4(),
    ))
    await db.flush()
    visit_id = uuid.uuid4()
    db.add(Visit(
        id=visit_id, visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient_id,
        facility_id=facility_id, visit_type="ipd", visit_date=datetime.now(timezone.utc),
        created_by=uuid.uuid4(),
    ))
    await db.flush()
    return patient_id, visit_id


async def test_reconcile_flags_occupied_bed_with_no_admission(db):
    """Deliberately seeded mismatch: bed says occupied, nothing points to it."""
    facility_id = await _make_facility(db)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id, bed_status="occupied")

    mismatches = await service.reconcile_bed_status(db, facility_id)

    assert len(mismatches) == 1
    assert mismatches[0]["bed_id"] == bed_id
    assert mismatches[0]["active_admission_id"] is None


async def test_reconcile_flags_vacant_bed_with_active_admission(db):
    """Deliberately seeded mismatch: bed says vacant, but an admission
    is actively pointing to it -- bypasses admit_patient() on purpose
    to simulate the mirror having drifted out of sync."""
    facility_id = await _make_facility(db)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id, bed_status="vacant")
    patient_id, visit_id = await _make_patient_and_visit(db, facility_id)

    admission_id = uuid.uuid4()
    db.add(Admission(
        id=admission_id, visit_id=visit_id, patient_id=patient_id, ward_id=ward_id, bed_id=bed_id,
        admitted_at=datetime.now(timezone.utc), status="admitted", created_by=uuid.uuid4(),
    ))
    await db.flush()

    mismatches = await service.reconcile_bed_status(db, facility_id)

    assert len(mismatches) == 1
    assert mismatches[0]["bed_id"] == bed_id
    assert mismatches[0]["active_admission_id"] == admission_id


async def test_reconcile_no_mismatch_when_consistent(db):
    facility_id = await _make_facility(db)
    # A properly-admitted bed (via the real service function, so bed
    # status and admission genuinely agree) plus a genuinely vacant one.
    ward_id, occupied_bed_id = await _make_ward_and_bed(db, facility_id, bed_status="vacant")
    _ward_id_2, vacant_bed_id = await _make_ward_and_bed(db, facility_id, bed_status="vacant")
    patient_id, visit_id = await _make_patient_and_visit(db, facility_id)

    await service.admit_patient(
        db, visit_id=visit_id, ward_id=ward_id, bed_id=occupied_bed_id, created_by=uuid.uuid4(),
    )

    mismatches = await service.reconcile_bed_status(db, facility_id)
    assert mismatches == []


async def test_reconcile_scoped_to_facility(db):
    facility_a = await _make_facility(db)
    facility_b = await _make_facility(db)
    _ward_a, _bed_a = await _make_ward_and_bed(db, facility_a, bed_status="occupied")  # mismatch in A
    _ward_b, _bed_b = await _make_ward_and_bed(db, facility_b, bed_status="occupied")  # mismatch in B

    mismatches = await service.reconcile_bed_status(db, facility_a)
    assert len(mismatches) == 1


async def test_reconcile_full_sweep_when_no_facility_given(db):
    facility_a = await _make_facility(db)
    facility_b = await _make_facility(db)
    await _make_ward_and_bed(db, facility_a, bed_status="occupied")
    await _make_ward_and_bed(db, facility_b, bed_status="occupied")

    mismatches = await service.reconcile_bed_status(db)
    assert len(mismatches) == 2
