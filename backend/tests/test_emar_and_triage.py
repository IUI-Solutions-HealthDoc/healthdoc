"""Tests for Suite 5: eMAR, ED Triage, Structured Lab Results & Urgency Propagation (HD-17 to HD-20)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.common.enums import MedicationAdministrationStatus
from app.emergency.models import EmergencyTriage, EmergencyTriageLog
from app.emergency.schemas import (
    EmergencyReTriageRequest,
    EmergencyTriageCreate,
    EmergencyTriageUpdate,
)
from app.emergency.service import (
    create_triage,
    get_emergency_metrics,
    list_active_triages,
    re_triage,
    update_triage,
)
from app.nursing.models import MedicationAdministration
from app.nursing.schemas import (
    MedicationAdministrationCreate,
)
from app.nursing.service import (
    acknowledge_administration,
    record_administration,
)
from app.orders.models import Prescription, PrescriptionItem
from app.orders.service import get_prescription_items
from app.pathology.analyte_service import evaluate_result_analytes
from app.pathology.models import LabAnalyte
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _setup_patient_and_admission(db):
    facility = Facility(
        id=uuid.uuid4(),
        name="Test Facility",
        code=f"TF{uuid.uuid4().hex[:4]}",
        state_code="RJ",
    )
    db.add(facility)

    doctor = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_{uuid.uuid4().hex[:6]}",
        username=f"doc_{uuid.uuid4().hex[:6]}",
        full_name="Dr. Attending",
        is_active=True,
    )
    db.add(doctor)

    patient = Patient(
        id=uuid.uuid4(),
        facility_id=facility.id,
        uhid=f"UH-{uuid.uuid4().hex[:6].upper()}",
        full_name="Emergency Patient",
        sex="male",
        age_years=35,
        status="active",
        identity_path="demographics_only",
        created_by=doctor.id,
    )
    db.add(patient)

    nurse = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_{uuid.uuid4().hex[:6]}",
        username=f"nurse_{uuid.uuid4().hex[:6]}",
        full_name="Nurse Charge",
        is_active=True,
    )
    db.add(nurse)

    # Fake admission & prescription
    prescription = Prescription(
        id=uuid.uuid4(),
        facility_id=facility.id,
        encounter_id=uuid.uuid4(),
        patient_id=patient.id,
        created_by=doctor.id,
    )
    db.add(prescription)

    item = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        medicine_name="Paracetamol",
        dosage="500mg",
        route="oral",
        status="prescribed",
        priority="routine",
    )
    db.add(item)
    await db.flush()

    return facility, patient, doctor, nurse, prescription, item


# ===========================================================================
# HD-17: eMAR Dose Identity, Concurrency Safeguards & Corrections
# ===========================================================================

async def test_emar_concurrency_and_dose_corrections(db):
    facility, patient, doctor, nurse, prescription, item = await _setup_patient_and_admission(db)
    admission_id = uuid.uuid4()
    scheduled = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)

    # 1. Record normal scheduled dose
    create_payload = MedicationAdministrationCreate(
        prescription_item_id=item.id,
        admission_id=admission_id,
        patient_id=patient.id,
        status="given",
        scheduled_at=scheduled,
        dose_given="500mg",
        route="oral",
    )
    admin_record = await record_administration(db, create_payload, recorded_by=nurse.id)
    assert admin_record.id is not None
    assert admin_record.is_correction is False
    assert admin_record.status == "given"

    # 2. Concurrency safeguard: attempt to record another dose for the exact same scheduled time
    duplicate_payload = MedicationAdministrationCreate(
        prescription_item_id=item.id,
        admission_id=admission_id,
        patient_id=patient.id,
        status="given",
        scheduled_at=scheduled,
        dose_given="500mg",
    )
    with pytest.raises(HTTPException) as exc_info:
        await record_administration(db, duplicate_payload, recorded_by=nurse.id)
    assert exc_info.value.status_code == 409
    assert "already recorded" in exc_info.value.detail

    # 3. Dose correction validation: reason must be >= 10 characters
    with pytest.raises(ValidationError):
        MedicationAdministrationCreate(
            prescription_item_id=item.id,
            admission_id=admission_id,
            patient_id=patient.id,
            status="given",
            dose_given="250mg",
            is_correction=True,
            correction_of_id=admin_record.id,
            correction_reason="short",  # < 10 chars
        )

    # 4. Valid dose correction: points to original dose, preserves original record intact
    correction_payload = MedicationAdministrationCreate(
        prescription_item_id=item.id,
        admission_id=admission_id,
        patient_id=patient.id,
        status="given",
        dose_given="250mg",
        is_correction=True,
        correction_of_id=admin_record.id,
        correction_reason="Patient vomited half of dose, administered partial replacement.",
    )
    correction_record = await record_administration(db, correction_payload, recorded_by=nurse.id)
    assert correction_record.is_correction is True
    assert correction_record.correction_of_id == admin_record.id
    assert correction_record.dose_given == "250mg"

    # Verify original dose was NOT overwritten in place
    orig_reload = await db.get(MedicationAdministration, admin_record.id)
    assert orig_reload.dose_given == "500mg"
    assert orig_reload.is_correction is False


async def test_emar_stopped_prescription_rejection(db):
    facility, patient, doctor, nurse, prescription, item = await _setup_patient_and_admission(db)
    item.status = "stopped"
    await db.flush()

    payload = MedicationAdministrationCreate(
        prescription_item_id=item.id,
        admission_id=uuid.uuid4(),
        patient_id=patient.id,
        status="given",
        dose_given="500mg",
    )
    with pytest.raises(HTTPException) as exc:
        await record_administration(db, payload, recorded_by=nurse.id)
    assert exc.value.status_code == 409
    assert "stopped" in exc.value.detail


async def test_emar_doctor_acknowledgement(db):
    facility, patient, doctor, nurse, prescription, item = await _setup_patient_and_admission(db)
    item.priority = "stat"
    await db.flush()

    payload = MedicationAdministrationCreate(
        prescription_item_id=item.id,
        admission_id=uuid.uuid4(),
        patient_id=patient.id,
        status="given",
        dose_given="1000mg",
        requires_acknowledgement=True,
    )
    record = await record_administration(db, payload, recorded_by=nurse.id)
    assert record.requires_acknowledgement is True
    assert record.acknowledged_by is None

    # Doctor acknowledges administration
    ack = await acknowledge_administration(
        db, record.id, acknowledged_by=doctor.id, notes="Verified STAT administration"
    )
    assert ack.acknowledged_by == doctor.id
    assert ack.acknowledged_at is not None
    assert "Verified STAT administration" in ack.notes


# ===========================================================================
# HD-18: ED Triage, Tracking Board, Re-Triage Audit & Metrics
# ===========================================================================

async def _emergency_visit(db, facility, patient, created_by):
    from app.opd.models import Visit

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-ED-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=facility.id,
        visit_type="emergency",
        status="registered",
        visit_date=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(visit)
    await db.flush()
    return visit


async def test_ed_triage_flow_and_retriage_audit(db):
    facility, patient, doctor, nurse, _, _ = await _setup_patient_and_admission(db)
    visit_id = (await _emergency_visit(db, facility, patient, nurse.id)).id

    # 1. Initial Triage
    triage_payload = EmergencyTriageCreate(
        patient_id=patient.id,
        visit_id=visit_id,
        acuity_level="urgent",
        chief_complaint="Severe abdominal pain and fever",
        triage_notes="Alert, tachycardic, guarding right lower quadrant",
        assigned_bay="Bay 3",
        assigned_doctor_id=doctor.id,
    )
    triage = await create_triage(
        db, triage_payload, facility_id=facility.id, triaged_by=nurse.id
    )
    assert triage.id is not None
    assert triage.acuity_level == "urgent"
    assert triage.status == "waiting"

    # 2. Re-Triage patient with mandatory justification
    with pytest.raises(ValidationError):
        # reason < 10 chars must fail schema validation
        EmergencyReTriageRequest(new_acuity="resuscitation", reason="worse")

    retriage_payload = EmergencyReTriageRequest(
        new_acuity="resuscitation",
        reason="Patient became unresponsive, acute hypotensive collapse.",
    )
    updated_triage = await re_triage(
        db, triage.id, retriage_payload, facility_id=facility.id, changed_by=doctor.id
    )
    assert updated_triage.acuity_level == "resuscitation"

    # Verify log entry in emergency_triage_logs
    board = await list_active_triages(db, facility.id)
    assert len(board) == 1
    item = board[0]
    assert item["acuity_level"] == "resuscitation"
    assert len(item["logs"]) == 1
    assert item["logs"][0].previous_acuity == "urgent"
    assert item["logs"][0].new_acuity == "resuscitation"
    assert item["logs"][0].reason == "Patient became unresponsive, acute hypotensive collapse."

    # 3. Update status to in_treatment -> records clinician_seen_at
    update_payload = EmergencyTriageUpdate(status="in_treatment", clinician_seen=True)
    in_tx = await update_triage(
        db, triage.id, update_payload, facility_id=facility.id, updated_by=doctor.id,
        updated_by_is_doctor=True,
    )
    assert in_tx.status == "in_treatment"
    assert in_tx.clinician_seen_at is not None
    assert in_tx.assigned_doctor_id == doctor.id

    # 4. ED Metrics Calculation
    metrics = await get_emergency_metrics(db, facility.id)
    assert metrics["active_census"] == 1
    assert metrics["in_treatment_count"] == 1
    assert metrics["resuscitation_count"] == 1
    assert metrics["urgent_count"] == 0


# ===========================================================================
# HD-19: Structured Lab Analytes & Reference Intervals
# ===========================================================================

async def test_lab_analyte_evaluation(db):
    # Insert test analytes for CBC
    hb = LabAnalyte(
        id=uuid.uuid4(),
        test_code="CBC",
        analyte_code="HEMOGLOBIN",
        analyte_name="Hemoglobin",
        value_type="numeric",
        unit="g/dL",
        reference_low=Decimal("12.0"),
        reference_high=Decimal("17.5"),
        critical_low=Decimal("7.0"),
        critical_high=Decimal("20.0"),
        is_required=True,
    )
    plt = LabAnalyte(
        id=uuid.uuid4(),
        test_code="CBC",
        analyte_code="PLATELETS",
        analyte_name="Platelet Count",
        value_type="numeric",
        unit="x10^3/uL",
        reference_low=Decimal("150.0"),
        reference_high=Decimal("450.0"),
        critical_low=Decimal("50.0"),
        critical_high=Decimal("1000.0"),
        is_required=False,
    )
    db.add_all([hb, plt])
    await db.flush()

    # 1. Normal values
    res_normal, crit_normal = await evaluate_result_analytes(
        db, "CBC", {"HEMOGLOBIN": 14.5, "PLATELETS": 250}
    )
    assert crit_normal == []
    assert res_normal["_analytes"]["HEMOGLOBIN"]["flag"] == "normal"
    assert res_normal["_analytes"]["PLATELETS"]["flag"] == "normal"

    # 2. Abnormal Low (not critical)
    res_abnormal, crit_abn = await evaluate_result_analytes(
        db, "CBC", {"HEMOGLOBIN": 10.2, "PLATELETS": 300}
    )
    assert crit_abn == []
    assert res_abnormal["_analytes"]["HEMOGLOBIN"]["flag"] == "abnormal_low"

    # 3. Critical Low (triggers critical alert)
    res_crit, crit_fields = await evaluate_result_analytes(
        db, "CBC", {"HEMOGLOBIN": 5.8, "PLATELETS": 200}
    )
    assert "HEMOGLOBIN" in crit_fields
    assert res_crit["_analytes"]["HEMOGLOBIN"]["flag"] == "critical_low"
    assert res_crit["_has_critical"] is True

    # 4. Missing required analyte raises ValueError
    with pytest.raises(ValueError, match="Missing required analyte"):
        await evaluate_result_analytes(db, "CBC", {"PLATELETS": 300})


# ===========================================================================
# HD-20: Urgency Propagation and Order Sorting
# ===========================================================================

async def test_prescription_items_urgency_ordering(db):
    facility, patient, doctor, _, prescription, _ = await _setup_patient_and_admission(db)

    r_item = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        medicine_name="Multivitamin",
        priority="routine",
    )
    u_item = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        medicine_name="Ceftriaxone",
        priority="urgent",
    )
    s_item = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        medicine_name="Adrenaline",
        priority="stat",
    )
    db.add_all([r_item, u_item, s_item])
    await db.flush()

    items = await get_prescription_items(db, prescription.id)
    priorities = [i.priority for i in items]

    # STAT items must come first, followed by URGENT, then ROUTINE
    assert priorities[0] == "stat"
    assert priorities[1] == "urgent"
    assert priorities[2] == "routine"


# QA 16-17 Oct 2026: second triage, re-triage to the same level, LWBS after
# seen, admit before seen, silent P1 discharge, another facility's triage.

async def _triaged(db, acuity="resuscitation"):
    facility, patient, doctor, nurse, _, _ = await _setup_patient_and_admission(db)
    visit = await _emergency_visit(db, facility, patient, nurse.id)
    triage = await create_triage(
        db,
        EmergencyTriageCreate(
            patient_id=patient.id, visit_id=visit.id, acuity_level=acuity, chief_complaint="Chest pain",
        ),
        facility_id=facility.id, triaged_by=nurse.id,
    )
    return facility, patient, doctor, nurse, visit, triage


async def test_a_second_initial_triage_of_one_visit_is_refused(db):
    from app.emergency.service import TriageRefused

    facility, patient, _, nurse, visit, _ = await _triaged(db)
    with pytest.raises(TriageRefused) as exc:
        await create_triage(
            db,
            EmergencyTriageCreate(
                patient_id=patient.id, visit_id=visit.id, acuity_level="non_urgent", chief_complaint="Again",
            ),
            facility_id=facility.id, triaged_by=nurse.id,
        )
    assert exc.value.code == "already_triaged"
    assert len(await list_active_triages(db, facility.id)) == 1


async def test_a_blank_chief_complaint_is_refused():
    with pytest.raises(ValidationError):
        EmergencyTriageCreate(
            patient_id=uuid.uuid4(), visit_id=uuid.uuid4(), acuity_level="urgent", chief_complaint="   ",
        )
    with pytest.raises(ValidationError):
        EmergencyReTriageRequest(new_acuity="urgent", reason="          x")


async def test_triage_of_another_facilitys_visit_is_not_found(db):
    from app.emergency.service import TriageRefused

    facility, patient, _, nurse, visit, triage = await _triaged(db)
    other = Facility(id=uuid.uuid4(), name="Other", code=f"OF{uuid.uuid4().hex[:4]}", state_code="RJ")
    db.add(other)
    await db.flush()
    with pytest.raises(TriageRefused) as exc:
        await re_triage(
            db, triage.id, EmergencyReTriageRequest(new_acuity="urgent", reason="Improving after fluids"),
            facility_id=other.id, changed_by=nurse.id,
        )
    assert exc.value.status == 404


async def test_re_triage_to_the_same_level_names_the_reason(db):
    from app.emergency.service import TriageRefused

    facility, _, doctor, _, _, triage = await _triaged(db)
    with pytest.raises(TriageRefused) as exc:
        await re_triage(
            db, triage.id, EmergencyReTriageRequest(new_acuity="resuscitation", reason="No change at all here"),
            facility_id=facility.id, changed_by=doctor.id,
        )
    assert exc.value.code == "acuity_unchanged"
    assert "different acuity" in exc.value.message


async def test_disposition_rules(db):
    from app.admissions.service import list_pending_admissions
    from app.emergency.service import TriageRefused

    facility, _, doctor, _, visit, triage = await _triaged(db)

    with pytest.raises(TriageRefused) as exc:
        await update_triage(
            db, triage.id, EmergencyTriageUpdate(disposition="admit"),
            facility_id=facility.id, updated_by=doctor.id,
        )
    assert exc.value.code == "admit_before_seen"

    await update_triage(
        db, triage.id, EmergencyTriageUpdate(clinician_seen=True),
        facility_id=facility.id, updated_by=doctor.id, updated_by_is_doctor=True,
    )
    with pytest.raises(TriageRefused) as exc:
        await update_triage(
            db, triage.id, EmergencyTriageUpdate(disposition="lwbs"),
            facility_id=facility.id, updated_by=doctor.id,
        )
    assert exc.value.code == "lwbs_after_seen"

    with pytest.raises(TriageRefused) as exc:
        await update_triage(
            db, triage.id, EmergencyTriageUpdate(disposition="discharge"),
            facility_id=facility.id, updated_by=doctor.id,
        )
    assert exc.value.code == "high_acuity_discharge_unconfirmed"

    admitted = await update_triage(
        db, triage.id, EmergencyTriageUpdate(disposition="admit", disposition_notes="Admit to ICU"),
        facility_id=facility.id, updated_by=doctor.id,
    )
    assert admitted.status == "admitted"
    queue = await list_pending_admissions(db, facility_id=facility.id)
    assert [row["visit_id"] for row in queue] == [visit.id]
    assert queue[0]["priority"] == "emergency"

    with pytest.raises(TriageRefused) as exc:
        await update_triage(
            db, triage.id, EmergencyTriageUpdate(disposition="discharge", confirm_high_acuity_discharge=True),
            facility_id=facility.id, updated_by=doctor.id,
        )
    assert exc.value.code == "triage_closed"


async def test_confirmed_discharge_closes_the_visit_and_leaves_the_worklist(db):
    from app.emergency.service import get_emergency_worklist

    facility, _, doctor, _, visit, triage = await _triaged(db, acuity="non_urgent")
    assert [i["visit_id"] for i in await get_emergency_worklist(db, facility.id)] == [visit.id]
    await update_triage(
        db, triage.id, EmergencyTriageUpdate(disposition="discharge"),
        facility_id=facility.id, updated_by=doctor.id,
    )
    assert visit.status == "completed"
    assert await get_emergency_worklist(db, facility.id) == []


async def test_census_counts_an_arrival_before_triage_and_door_time_runs_from_arrival(db):
    facility, patient, doctor, nurse, _, _ = await _setup_patient_and_admission(db)
    visit = await _emergency_visit(db, facility, patient, nurse.id)
    metrics = await get_emergency_metrics(db, facility.id)
    assert metrics["active_census"] == 1
    assert metrics["awaiting_triage_count"] == 1

    visit.created_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    triage = await create_triage(
        db,
        EmergencyTriageCreate(
            patient_id=patient.id, visit_id=visit.id, acuity_level="urgent", chief_complaint="Fall",
            triaged_at=datetime.now(timezone.utc) - timedelta(minutes=9),
        ),
        facility_id=facility.id, triaged_by=nurse.id,
    )
    await update_triage(
        db, triage.id, EmergencyTriageUpdate(clinician_seen=True),
        facility_id=facility.id, updated_by=doctor.id, updated_by_is_doctor=True,
    )
    board = await list_active_triages(db, facility.id)
    assert board[0]["door_to_clinician_minutes"] >= 19
    metrics = await get_emergency_metrics(db, facility.id)
    assert metrics["active_census"] == 1
    assert metrics["awaiting_triage_count"] == 0
    assert metrics["avg_door_to_clinician_minutes"] >= 19
