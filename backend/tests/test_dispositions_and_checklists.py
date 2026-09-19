"""Tests for HD-13 to HD-16: Clinical dispositions, admission checklists, and admission charts.
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from app.admissions import service
from app.admissions.models import Admission, Bed, ClinicalDisposition, Ward
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _make_facility(db):
    facility_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Hospital", state_code="DL"))
    await db.flush()
    return facility_id


async def _make_user(db, facility_id):
    user_id = uuid.uuid4()
    db.add(User(
        id=user_id,
        facility_id=facility_id,
        keycloak_sub=f"sub_{uuid.uuid4().hex[:12]}",
        username=f"doc_{uuid.uuid4().hex[:6]}",
        email=f"doc_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Dr. Clinical Specialist",
        is_active=True,
    ))
    await db.flush()
    return user_id


async def _make_patient(db, facility_id, user_id):
    patient_id = uuid.uuid4()
    db.add(Patient(
        id=patient_id,
        uhid=f"UHID{uuid.uuid4().hex[:8]}",
        full_name="John Inpatient",
        sex="male",
        dob=date(1985, 5, 20),
        facility_id=facility_id,
        identity_path="demographics_only",
        identity_status="verified",
        created_by=user_id,
    ))
    await db.flush()
    return patient_id


async def _make_visit(db, patient_id, facility_id, user_id):
    visit_id = uuid.uuid4()
    db.add(Visit(
        id=visit_id,
        visit_number=f"V{uuid.uuid4().hex[:8]}",
        patient_id=patient_id,
        facility_id=facility_id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        created_by=user_id,
    ))
    await db.flush()
    return visit_id


async def _make_ward_and_bed(db, facility_id, bed_status="vacant"):
    ward_id = uuid.uuid4()
    bed_id = uuid.uuid4()
    db.add(Ward(id=ward_id, name="Cardiology Ward", facility_id=facility_id))
    db.add(Bed(id=bed_id, ward_id=ward_id, bed_number="BED-01", status=bed_status))
    await db.flush()
    return ward_id, bed_id


async def test_create_disposition_and_priority_queue(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id_1 = await _make_patient(db, facility_id, user_id)
    visit_id_1 = await _make_visit(db, patient_id_1, facility_id, user_id)
    ward_id, _ = await _make_ward_and_bed(db, facility_id)

    # 1. Routine disposition
    disp1 = await service.create_clinical_disposition(
        db,
        facility_id=facility_id,
        patient_id=patient_id_1,
        visit_id=visit_id_1,
        disposition_type="admit",
        priority="routine",
        recommended_ward_id=ward_id,
        reason="Scheduled diagnostic workup",
        created_by=user_id,
    )
    assert disp1.id is not None
    assert disp1.status == "pending"

    # 2. Emergency disposition for a second patient
    patient_id_2 = await _make_patient(db, facility_id, user_id)
    visit_id_2 = await _make_visit(db, patient_id_2, facility_id, user_id)
    disp2 = await service.create_clinical_disposition(
        db,
        facility_id=facility_id,
        patient_id=patient_id_2,
        visit_id=visit_id_2,
        disposition_type="admit",
        priority="emergency",
        recommended_ward_id=ward_id,
        reason="Acute coronary syndrome",
        created_by=user_id,
    )

    # 3. Query "To Admit" queue — emergency must be ranked ahead of routine
    pending = await service.list_pending_admissions(db, facility_id=facility_id)
    assert len(pending) >= 2
    # Verify emergency comes first
    found_ids = [item["disposition_id"] for item in pending]
    assert found_ids.index(disp2.id) < found_ids.index(disp1.id)

    # Check populated fields
    disp2_item = next(item for item in pending if item["disposition_id"] == disp2.id)
    assert disp2_item["patient_name"] == "John Inpatient"
    assert disp2_item["priority"] == "emergency"
    assert disp2_item["recommended_ward_name"] == "Cardiology Ward"
    assert disp2_item["doctor_name"] == "Dr. Clinical Specialist"


async def test_admit_resolves_disposition_and_seeds_checklist(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id = await _make_patient(db, facility_id, user_id)
    visit_id = await _make_visit(db, patient_id, facility_id, user_id)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id)

    # Create pending admit disposition
    disp = await service.create_clinical_disposition(
        db,
        facility_id=facility_id,
        patient_id=patient_id,
        visit_id=visit_id,
        disposition_type="admit",
        priority="urgent",
        recommended_ward_id=ward_id,
        reason="Pneumonia requiring IV antibiotics",
        created_by=user_id,
    )
    assert disp.status == "pending"

    # Admit the patient
    admission = await service.admit_patient(
        db,
        visit_id=visit_id,
        ward_id=ward_id,
        bed_id=bed_id,
        created_by=user_id,
        reason="Pneumonia admission",
        facility_id=facility_id,
    )
    assert admission.status == "admitted"

    # Verify disposition status updated to 'admitted'
    refreshed_disp = await db.get(ClinicalDisposition, disp.id)
    assert refreshed_disp.status == "admitted"

    # Verify 6 standard checklist tasks were initialized
    checklist = await service.get_admission_checklist(db, admission.id, facility_id)
    assert len(checklist) == 6
    task_codes = {t["task_code"] for t in checklist}
    expected_codes = {
        "id_wristband",
        "baseline_vitals",
        "allergy_diet",
        "med_reconciliation",
        "fall_safety_risk",
        "ward_orientation",
    }
    assert task_codes == expected_codes
    for t in checklist:
        assert t["status"] == "pending"


async def test_checklist_update_and_mandatory_skip_reason(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id = await _make_patient(db, facility_id, user_id)
    visit_id = await _make_visit(db, patient_id, facility_id, user_id)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id)

    admission = await service.admit_patient(
        db,
        visit_id=visit_id,
        ward_id=ward_id,
        bed_id=bed_id,
        created_by=user_id,
        facility_id=facility_id,
    )

    checklist = await service.get_admission_checklist(db, admission.id, facility_id)
    wristband_task = next(t for t in checklist if t["task_code"] == "id_wristband")
    vitals_task = next(t for t in checklist if t["task_code"] == "baseline_vitals")

    # 1. Mark completed
    updated_wristband = await service.update_checklist_task(
        db,
        admission_id=admission.id,
        task_id=wristband_task["id"],
        status="completed",
        notes="Wristband barcode verified with attendant",
        updated_by=user_id,
        facility_id=facility_id,
    )
    assert updated_wristband["status"] == "completed"
    assert updated_wristband["completed_at"] is not None
    assert updated_wristband["completed_by"] == user_id
    assert updated_wristband["completed_by_name"] == "Dr. Clinical Specialist"

    # 2. Try to skip without justification -> Must fail
    with pytest.raises(service.ChecklistSkipReasonRequired):
        await service.update_checklist_task(
            db,
            admission_id=admission.id,
            task_id=vitals_task["id"],
            status="skipped",
            skipped_reason="   ",  # whitespace only
            updated_by=user_id,
            facility_id=facility_id,
        )

    # 3. Skip with valid clinical justification -> Must succeed
    updated_vitals = await service.update_checklist_task(
        db,
        admission_id=admission.id,
        task_id=vitals_task["id"],
        status="skipped",
        skipped_reason="Emergency intubation in progress; vitals captured via monitor",
        updated_by=user_id,
        facility_id=facility_id,
    )
    assert updated_vitals["status"] == "skipped"
    assert updated_vitals["skipped_reason"] == "Emergency intubation in progress; vitals captured via monitor"


async def test_admission_chart_aggregation(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id = await _make_patient(db, facility_id, user_id)
    visit_id = await _make_visit(db, patient_id, facility_id, user_id)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id)

    admission = await service.admit_patient(
        db,
        visit_id=visit_id,
        ward_id=ward_id,
        bed_id=bed_id,
        created_by=user_id,
        reason="Heart failure decompensation",
        facility_id=facility_id,
    )

    # Complete 1 task
    checklist = await service.get_admission_checklist(db, admission.id, facility_id)
    await service.update_checklist_task(
        db,
        admission_id=admission.id,
        task_id=checklist[0]["id"],
        status="completed",
        updated_by=user_id,
        facility_id=facility_id,
    )

    chart = await service.get_admission_chart(db, admission.id, facility_id)
    assert chart["admission_id"] == admission.id
    assert chart["patient"]["full_name"] == "John Inpatient"
    assert chart["patient"]["sex"] == "male"
    assert chart["admission"]["ward_name"] == "Cardiology Ward"
    assert chart["admission"]["bed_number"] == "BED-01"
    assert chart["checklist_summary"]["total"] == 6
    assert chart["checklist_summary"]["completed"] == 1
    assert chart["checklist_summary"]["pending"] == 5
    assert chart["checklist_summary"]["percent_complete"] == 17


async def test_list_pending_discharges(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id = await _make_patient(db, facility_id, user_id)
    visit_id = await _make_visit(db, patient_id, facility_id, user_id)
    ward_id, bed_id = await _make_ward_and_bed(db, facility_id)

    admission = await service.admit_patient(
        db,
        visit_id=visit_id,
        ward_id=ward_id,
        bed_id=bed_id,
        created_by=user_id,
        facility_id=facility_id,
    )

    # Doctor records discharge disposition
    disp = await service.create_clinical_disposition(
        db,
        facility_id=facility_id,
        patient_id=patient_id,
        visit_id=visit_id,
        disposition_type="discharge",
        priority="routine",
        reason="Clinically stable, oral medication switched",
        created_by=user_id,
    )

    discharges = await service.list_pending_discharges(db, facility_id=facility_id)
    assert len(discharges) >= 1
    d_item = next(d for d in discharges if d["admission_id"] == admission.id)
    assert d_item["patient_name"] == "John Inpatient"
    assert d_item["bed_number"] == "BED-01"
    assert d_item["reason"] == "Clinically stable, oral medication switched"


async def test_transfer_patient_with_concurrency_lock(db):
    facility_id = await _make_facility(db)
    user_id = await _make_user(db, facility_id)
    patient_id = await _make_patient(db, facility_id, user_id)
    visit_id = await _make_visit(db, patient_id, facility_id, user_id)
    ward_id_1, bed_id_1 = await _make_ward_and_bed(db, facility_id)
    ward_id_2, bed_id_2 = await _make_ward_and_bed(db, facility_id)

    admission = await service.admit_patient(
        db,
        visit_id=visit_id,
        ward_id=ward_id_1,
        bed_id=bed_id_1,
        created_by=user_id,
        facility_id=facility_id,
    )

    # Transfer to bed 2
    transferred = await service.transfer_patient(
        db,
        admission=admission,
        to_ward_id=ward_id_2,
        to_bed_id=bed_id_2,
        moved_by=user_id,
        reason="Shifted to step-down unit",
        facility_id=facility_id,
    )
    assert transferred.ward_id == ward_id_2
    assert transferred.bed_id == bed_id_2

    # Check old bed is now vacant and new bed is occupied
    old_bed = await db.get(Bed, bed_id_1)
    new_bed = await db.get(Bed, bed_id_2)
    assert old_bed.status == "vacant"
    assert new_bed.status == "occupied"
