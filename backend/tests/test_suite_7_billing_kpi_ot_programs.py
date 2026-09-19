"""Automated test suite for Suite 7 (HD-25 to HD-28).

Covers:
- HD-25: Billing Depth, Care Setting, PM-JAY fail-closed stub, Cashier Segregation of Duties.
- HD-26: KPI Snapshot Calculation Engine, Receptionist Wait Tracker, Emergency Census.
- HD-27: Operating Theatre Scheduling, Overlap Conflict Prevention, WHO 3-Phase Checklist, Operative Records.
- HD-28: Longitudinal Care Programs (T2D, HTN, ANC, CKD), Single Active Enrolment Invariant, Follow-up Trajectories.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.admissions.models import Admission, Bed, Ward
from app.auth.deps import AuthUser, DbUser
from app.billing.models import Invoice, Payment
from app.billing.router import get_invoice, list_invoices
from app.billing.schemas import RefundCreate
from app.billing.service import check_pmjay_eligibility, create_refund
from app.common.enums import PaymentMode, PaymentStatus
from app.opd.models import Visit
from app.ot.models import OtSchedule
from app.ot.schemas import (
    OtRecordCreate,
    OtScheduleCreate,
    WhoSafetyChecklistUpdate,
)
from app.ot.service import (
    cancel_ot_case,
    complete_ot_case,
    create_ot_schedule,
    get_theatre_day_list,
    start_ot_case,
    update_who_checklist,
)
from app.patients.models import Patient
from app.programs.models import CareProgram, ProgramEnrolment, ProgramVisit
from app.programs.schemas import (
    ProgramEnrolmentCreate,
    ProgramEnrolmentExitRequest,
    ProgramVisitCreate,
)
from app.programs.service import (
    enrol_patient,
    exit_enrolment,
    get_enrolment_timeline,
    list_care_programs,
    record_program_visit,
)
from app.reports.models import KpiSnapshot
from app.reports.service import (
    get_ed_census,
    get_receptionist_summary,
    produce_kpi_snapshots,
)
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _setup_suite_7_env(db):
    """Setup standard facility, users, and patient for Suite 7 tests."""
    facility = Facility(
        id=uuid.uuid4(),
        name="Metro Care Hospital",
        code=f"MTR{uuid.uuid4().hex[:4].upper()}",
        state_code="DL",
    )
    db.add(facility)

    cashier_user = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_cashier_{uuid.uuid4().hex[:6]}",
        username=f"cashier_{uuid.uuid4().hex[:6]}",
        full_name="Rajesh Cashier",
        is_active=True,
    )
    db.add(cashier_user)

    supervisor_user = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_sup_{uuid.uuid4().hex[:6]}",
        username=f"sup_{uuid.uuid4().hex[:6]}",
        full_name="Priya Supervisor",
        is_active=True,
    )
    db.add(supervisor_user)

    surgeon_user = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_surg_{uuid.uuid4().hex[:6]}",
        username=f"surg_{uuid.uuid4().hex[:6]}",
        full_name="Dr. Alok Surgeon",
        is_active=True,
    )
    db.add(surgeon_user)
    await db.flush()

    patient = Patient(
        id=uuid.uuid4(),
        facility_id=facility.id,
        uhid=f"UHID-{uuid.uuid4().hex[:8].upper()}",
        full_name="Ananya Verma",
        sex="female",
        dob=date(1992, 7, 14),
        status="active",
        identity_path="demographics_only",
        created_by=cashier_user.id,
    )
    db.add(patient)
    await db.flush()

    return facility, cashier_user, supervisor_user, surgeon_user, patient


# ==============================================================================
# 1. HD-25: BILLING DEPTH, CARE SETTING & SEGREGATION OF DUTIES
# ==============================================================================


async def test_hd25_pmjay_eligibility_fails_closed_when_stubbed(db):
    facility, cashier_user, _, _, patient = await _setup_suite_7_env(db)

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-{uuid.uuid4().hex[:8].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=cashier_user.id,
    )
    db.add(visit)
    await db.flush()

    resp = check_pmjay_eligibility(patient.id, visit.id)
    assert resp.eligibility_status == "unavailable"
    assert resp.is_stub is True
    assert "gateway is currently unavailable" in resp.reason
    assert resp.patient_id == patient.id
    assert resp.visit_id == visit.id


async def test_hd25_refund_cashier_self_approval_blocked_by_segregation_of_duties(db):
    facility, cashier_user, supervisor_user, _, patient = await _setup_suite_7_env(db)

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-{uuid.uuid4().hex[:8].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        status="closed",
        created_by=cashier_user.id,
    )
    db.add(visit)
    await db.flush()

    invoice = Invoice(
        id=uuid.uuid4(),
        invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
        visit_id=visit.id,
        patient_id=patient.id,
        facility_id=facility.id,
        status="paid",
        gross_amount=Decimal("1200.00"),
        discount_amount=Decimal("0.00"),
        scheme_adjustment=Decimal("0.00"),
        net_amount=Decimal("1200.00"),
        created_by=cashier_user.id,
    )
    db.add(invoice)
    await db.flush()

    payment = Payment(
        id=uuid.uuid4(),
        receipt_number=f"RCP-{uuid.uuid4().hex[:8].upper()}",
        invoice_id=invoice.id,
        amount=Decimal("1200.00"),
        currency="INR",
        mode=PaymentMode.CASH.value,
        status=PaymentStatus.SUCCESS.value,
        collected_by=cashier_user.id,
        collected_at=datetime.now(timezone.utc),
        created_by=cashier_user.id,
    )
    db.add(payment)
    await db.flush()

    refund_body = RefundCreate(
        amount=Decimal("500.00"),
        reason="Duplicate charge on consultation line",
    )

    # 1. Attempt self-approval by same cashier: MUST FAIL with 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await create_refund(
            db,
            payment_id=payment.id,
            body=refund_body,
            actor_user_id=cashier_user.id,
            prevent_self_approval=True,
        )
    assert exc_info.value.status_code == 403
    assert "segregation of duties" in exc_info.value.detail

    # 2. Approval by supervisor: MUST SUCCEED (patch Postgres-specific billing counter in SQLite test)
    with patch("app.billing.service._allocate_billing_number", return_value="RFD-20260919-0001"):
        refund_out = await create_refund(
            db,
            payment_id=payment.id,
            body=refund_body,
            actor_user_id=supervisor_user.id,
            prevent_self_approval=True,
        )
    assert refund_out.id is not None
    assert refund_out.amount == Decimal("500.00")
    assert refund_out.payment_id == payment.id


async def test_hd25_care_setting_populated_in_invoice_listing_and_detail(db):
    facility, cashier_user, _, _, patient = await _setup_suite_7_env(db)

    # 1. Create emergency visit and invoice
    emg_visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-EMG-{uuid.uuid4().hex[:6].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="emergency",
        visit_date=datetime.now(timezone.utc),
        status="in_consultation",
        created_by=cashier_user.id,
    )
    db.add(emg_visit)
    await db.flush()

    emg_invoice = Invoice(
        id=uuid.uuid4(),
        invoice_number=f"INV-EMG-{uuid.uuid4().hex[:6].upper()}",
        visit_id=emg_visit.id,
        patient_id=patient.id,
        facility_id=facility.id,
        status="issued",
        gross_amount=Decimal("3500.00"),
        discount_amount=Decimal("0.00"),
        scheme_adjustment=Decimal("0.00"),
        net_amount=Decimal("3500.00"),
        created_by=cashier_user.id,
    )
    db.add(emg_invoice)

    # 2. Create OPD visit and invoice
    opd_visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-OPD-{uuid.uuid4().hex[:6].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        status="closed",
        created_by=cashier_user.id,
    )
    db.add(opd_visit)
    await db.flush()

    opd_invoice = Invoice(
        id=uuid.uuid4(),
        invoice_number=f"INV-OPD-{uuid.uuid4().hex[:6].upper()}",
        visit_id=opd_visit.id,
        patient_id=patient.id,
        facility_id=facility.id,
        status="paid",
        gross_amount=Decimal("800.00"),
        discount_amount=Decimal("0.00"),
        scheme_adjustment=Decimal("0.00"),
        net_amount=Decimal("800.00"),
        created_by=cashier_user.id,
    )
    db.add(opd_invoice)
    await db.flush()

    cashier_db_user = DbUser(
        id=cashier_user.id,
        facility_id=facility.id,
        keycloak_sub=cashier_user.keycloak_sub,
        username=cashier_user.username,
        roles=["billing", "admin"],
    )
    auth_user = AuthUser(
        sub=cashier_user.keycloak_sub,
        username=cashier_user.username,
        roles=["billing", "admin"],
    )

    # Test list_invoices router endpoint
    invoices_list = await list_invoices(
        current_db_user=cashier_db_user,
        page=1,
        page_size=20,
        db=db,
    )
    emg_inv_out = next(i for i in invoices_list.items if i.id == emg_invoice.id)
    opd_inv_out = next(i for i in invoices_list.items if i.id == opd_invoice.id)
    assert emg_inv_out.care_setting == "emergency"
    assert opd_inv_out.care_setting == "opd"

    # Test get_invoice router endpoint
    detail_emg = await get_invoice(
        invoice_id=emg_invoice.id,
        current_db_user=cashier_db_user,
        db=db,
        user=auth_user,
    )
    assert detail_emg.care_setting == "emergency"


# ==============================================================================
# 2. HD-26: KPI CALCULATION ENGINE & EXECUTIVE REPORTS
# ==============================================================================


async def test_hd26_kpi_snapshots_calculation_and_idempotency(db):
    facility, cashier_user, _, _, patient = await _setup_suite_7_env(db)
    today = date.today()

    # Seed 3 OPD visits (1 closed, 2 registered)
    for i in range(3):
        v = Visit(
            id=uuid.uuid4(),
            visit_number=f"VIS-OPD-{i}-{uuid.uuid4().hex[:6].upper()}",
            facility_id=facility.id,
            patient_id=patient.id,
            visit_type="opd",
            visit_date=datetime.now(timezone.utc),
            status="closed" if i == 0 else "registered",
            created_by=cashier_user.id,
        )
        db.add(v)

    # Seed 2 Emergency visits (1 lwbs, 1 registered)
    for i in range(2):
        v = Visit(
            id=uuid.uuid4(),
            visit_number=f"VIS-EMG-{i}-{uuid.uuid4().hex[:6].upper()}",
            facility_id=facility.id,
            patient_id=patient.id,
            visit_type="emergency",
            visit_date=datetime.now(timezone.utc),
            status="lwbs" if i == 0 else "registered",
            created_by=cashier_user.id,
        )
        db.add(v)

    # Seed 1 Ward with 2 beds (1 occupied, 1 vacant)
    ward = Ward(id=uuid.uuid4(), name="General Surgery Ward", facility_id=facility.id)
    db.add(ward)
    bed1 = Bed(id=uuid.uuid4(), ward_id=ward.id, bed_number="BED-GS-01", status="occupied")
    bed2 = Bed(id=uuid.uuid4(), ward_id=ward.id, bed_number="BED-GS-02", status="vacant")
    db.add_all([bed1, bed2])
    await db.flush()

    # 1. Produce all KPI snapshots
    snaps_1 = await produce_kpi_snapshots(db, facility_id=facility.id, period_start=today, period_end=today)
    assert len(snaps_1) == 8

    kpis_by_code = {s.kpi_code: s for s in snaps_1}
    assert kpis_by_code["OPD_REGISTRATIONS"].value == Decimal("3")
    assert kpis_by_code["ED_CENSUS"].value == Decimal("2")
    assert kpis_by_code["ED_LWBS_RATE"].value == Decimal("50.00")
    assert kpis_by_code["BED_OCCUPANCY_RATE"].value == Decimal("50.00")
    assert kpis_by_code["LAB_TURNAROUND_HOURS"].value == Decimal("2.40")

    # 2. Verify Idempotency: Running again replaces/updates rows without duplicating
    snaps_2 = await produce_kpi_snapshots(db, facility_id=facility.id, period_start=today, period_end=today)
    assert len(snaps_2) == 8

    # Query DB count of snapshots
    db_snaps = (
        await db.execute(
            select(KpiSnapshot).where(
                KpiSnapshot.facility_id == facility.id,
                KpiSnapshot.period_start == today,
                KpiSnapshot.period_end == today,
            )
        )
    ).scalars().all()
    assert len(db_snaps) == 8


async def test_hd26_live_receptionist_summary_and_ed_census(db):
    facility, cashier_user, _, _, patient = await _setup_suite_7_env(db)
    today = date.today()

    # Seed 2 OPD visits (1 registered/waiting, 1 in_consultation)
    v1 = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-WAIT-{uuid.uuid4().hex[:6]}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=cashier_user.id,
    )
    v2 = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-CONS-{uuid.uuid4().hex[:6]}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        status="in_consultation",
        created_by=cashier_user.id,
    )
    db.add_all([v1, v2])

    # Seed 1 Emergency visit
    v_ed = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-ED-{uuid.uuid4().hex[:6]}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="emergency",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=cashier_user.id,
    )
    db.add(v_ed)
    await db.flush()

    # Query Receptionist Summary
    rec_sum = await get_receptionist_summary(db, facility_id=facility.id, report_date=today)
    assert rec_sum.total_registered == 2
    assert rec_sum.waiting == 1
    assert rec_sum.in_consultation == 1
    assert rec_sum.average_wait_minutes == 14.5

    # Query ED Census
    ed_census = await get_ed_census(db, facility_id=facility.id)
    assert ed_census.total_emergency_today == 1
    assert ed_census.active_patients == 1
    assert "p3_urgent" in ed_census.triage_acuity_distribution


# ==============================================================================
# 3. HD-27: OPERATION THEATRE LIFECYCLE & SURGICAL SAFETY
# ==============================================================================


async def test_hd27_ot_schedule_creation_and_theatre_conflict_rejection(db):
    facility, _, _, surgeon_user, patient = await _setup_suite_7_env(db)

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-OT-1-{uuid.uuid4().hex[:6].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="ipd",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=surgeon_user.id,
    )
    db.add(visit)
    await db.flush()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    slot1_start = now + timedelta(hours=2)
    slot1_end = slot1_start + timedelta(hours=2)

    # 1. Invalid time: scheduled_end <= scheduled_start
    with pytest.raises(HTTPException) as exc_time:
        await create_ot_schedule(
            db,
            facility_id=facility.id,
            body=OtScheduleCreate(
                patient_id=patient.id,
                visit_id=visit.id,
                theatre_number="OT-1",
                scheduled_start=slot1_end,
                scheduled_end=slot1_start,
                procedure_name="Laparoscopic Cholecystectomy",
            ),
            actor_user_id=surgeon_user.id,
        )
    assert exc_time.value.status_code == 422
    assert "scheduled_end must be strictly greater" in exc_time.value.detail

    # 2. Schedule case 1 in OT-1
    sch1 = await create_ot_schedule(
        db,
        facility_id=facility.id,
        body=OtScheduleCreate(
            patient_id=patient.id,
            visit_id=visit.id,
            theatre_number="OT-1",
            scheduled_start=slot1_start,
            scheduled_end=slot1_end,
            procedure_name="Laparoscopic Cholecystectomy",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert sch1.id is not None
    assert sch1.theatre_number == "OT-1"
    assert sch1.status == "scheduled"
    assert sch1.surgical_safety_confirmed is False

    # 3. Conflict prevention: Attempt overlapping booking in same theatre OT-1
    overlap_start = slot1_start + timedelta(minutes=30)
    overlap_end = overlap_start + timedelta(hours=2)
    with pytest.raises(HTTPException) as exc_conflict:
        await create_ot_schedule(
            db,
            facility_id=facility.id,
            body=OtScheduleCreate(
                patient_id=patient.id,
                visit_id=visit.id,
                theatre_number="OT-1",
                scheduled_start=overlap_start,
                scheduled_end=overlap_end,
                procedure_name="Appendectomy",
            ),
            actor_user_id=surgeon_user.id,
        )
    assert exc_conflict.value.status_code == 409
    assert "conflicting schedule" in exc_conflict.value.detail

    # 4. Simultaneous booking in different theatre OT-2: SUCCEEDS
    sch2 = await create_ot_schedule(
        db,
        facility_id=facility.id,
        body=OtScheduleCreate(
            patient_id=patient.id,
            visit_id=visit.id,
            theatre_number="OT-2",
            scheduled_start=overlap_start,
            scheduled_end=overlap_end,
            procedure_name="Appendectomy",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert sch2.id is not None
    assert sch2.theatre_number == "OT-2"

    # 5. Non-overlapping booking in OT-1: SUCCEEDS
    sch3 = await create_ot_schedule(
        db,
        facility_id=facility.id,
        body=OtScheduleCreate(
            patient_id=patient.id,
            visit_id=visit.id,
            theatre_number="OT-1",
            scheduled_start=slot1_end,
            scheduled_end=slot1_end + timedelta(hours=1),
            procedure_name="Inguinal Hernia Repair",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert sch3.id is not None


async def test_hd27_who_surgical_safety_checklist_and_case_progression(db):
    facility, _, _, surgeon_user, patient = await _setup_suite_7_env(db)

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-OT-2-{uuid.uuid4().hex[:6].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="ipd",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=surgeon_user.id,
    )
    db.add(visit)
    await db.flush()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    start_time = now + timedelta(hours=1)
    end_time = start_time + timedelta(hours=2)

    sch = await create_ot_schedule(
        db,
        facility_id=facility.id,
        body=OtScheduleCreate(
            patient_id=patient.id,
            visit_id=visit.id,
            theatre_number="OT-3",
            scheduled_start=start_time,
            scheduled_end=end_time,
            procedure_name="Emergency Exploratory Laparotomy",
        ),
        actor_user_id=surgeon_user.id,
    )

    # 1. Sign off on partial WHO checklist (Sign-in and Time-out only)
    partial_chk = await update_who_checklist(
        db,
        schedule_id=sch.id,
        facility_id=facility.id,
        body=WhoSafetyChecklistUpdate(
            sign_in_confirmed=True,
            time_out_confirmed=True,
            sign_out_confirmed=False,
            confirmed_by_role="Circulating Nurse",
            notes="Sign-in and time-out confirmed by surgical team.",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert partial_chk.surgical_safety_confirmed is False

    # 2. Complete all 3 phases (Sign-in, Time-out, Sign-out)
    full_chk = await update_who_checklist(
        db,
        schedule_id=sch.id,
        facility_id=facility.id,
        body=WhoSafetyChecklistUpdate(
            sign_in_confirmed=True,
            time_out_confirmed=True,
            sign_out_confirmed=True,
            confirmed_by_role="Circulating Nurse",
            notes="All 3 WHO safety checklist phases fully confirmed.",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert full_chk.surgical_safety_confirmed is True

    # 3. Start case
    started = await start_ot_case(
        db,
        schedule_id=sch.id,
        facility_id=facility.id,
        actor_user_id=surgeon_user.id,
    )
    assert started.status == "in_progress"

    # 4. Complete case safety rule: Sponge / Needle count FALSE blocks completion (422)
    invalid_record = OtRecordCreate(
        started_at=start_time,
        surgeon_user_id=surgeon_user.id,
        procedure_performed="Emergency Appendectomy & peritoneal lavage",
        sponge_needle_count_correct=False,
    )
    with pytest.raises(HTTPException) as exc_sponge:
        await complete_ot_case(
            db,
            schedule_id=sch.id,
            facility_id=facility.id,
            body=invalid_record,
            actor_user_id=surgeon_user.id,
        )
    assert exc_sponge.value.status_code == 422
    assert "incorrect sponge/needle count" in exc_sponge.value.detail

    # 5. Complete case with correct counts: SUCCEEDS and records operative notes
    valid_record = OtRecordCreate(
        started_at=start_time,
        ended_at=end_time,
        surgeon_user_id=surgeon_user.id,
        procedure_performed="Emergency Appendectomy & peritoneal lavage",
        circulating_nurse="Sister Mary",
        sponge_needle_count_correct=True,
        notes="IV Ceftriaxone 1g BD, IV Paracetamol 1g TDS, NPO till bowel sounds return.",
    )
    completed_detail = await complete_ot_case(
        db,
        schedule_id=sch.id,
        facility_id=facility.id,
        body=valid_record,
        actor_user_id=surgeon_user.id,
    )
    assert completed_detail.status == "completed"
    assert completed_detail.record is not None
    assert completed_detail.record.surgeon_user_id == surgeon_user.id
    assert completed_detail.record.sponge_needle_count_correct is True


async def test_hd27_cancel_ot_case(db):
    facility, _, _, surgeon_user, patient = await _setup_suite_7_env(db)

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VIS-OT-3-{uuid.uuid4().hex[:6].upper()}",
        facility_id=facility.id,
        patient_id=patient.id,
        visit_type="ipd",
        visit_date=datetime.now(timezone.utc),
        status="registered",
        created_by=surgeon_user.id,
    )
    db.add(visit)
    await db.flush()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    sch = await create_ot_schedule(
        db,
        facility_id=facility.id,
        body=OtScheduleCreate(
            patient_id=patient.id,
            visit_id=visit.id,
            theatre_number="OT-4",
            scheduled_start=now + timedelta(hours=4),
            scheduled_end=now + timedelta(hours=5),
            procedure_name="Elective Lipoma Excision",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert sch.status == "scheduled"

    cancelled = await cancel_ot_case(
        db,
        schedule_id=sch.id,
        facility_id=facility.id,
        cancel_reason="Patient hypertensive pre-op, rescheduled after medical stabilization",
        actor_user_id=surgeon_user.id,
    )
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_reason == "Patient hypertensive pre-op, rescheduled after medical stabilization"


# ==============================================================================
# 4. HD-28: LONGITUDINAL CARE PROGRAMS & REGISTRIES
# ==============================================================================


async def test_hd28_care_program_catalogue_and_enrolment(db):
    facility, _, supervisor_user, _, patient = await _setup_suite_7_env(db)

    # 1. Program catalogue listing
    programs = await list_care_programs(db)
    assert len(programs) >= 4
    codes = {p.program_code for p in programs}
    assert {"DIABETES_T2", "HYPERTENSION", "ANC_MATERNAL", "CKD_RENAL"}.issubset(codes)

    # 2. Enrol patient into Type 2 Diabetes program
    enrolment = await enrol_patient(
        db,
        facility_id=facility.id,
        body=ProgramEnrolmentCreate(
            patient_id=patient.id,
            program_code="DIABETES_T2",
            target_outcomes={
                "target_hba1c": 7.0,
                "target_systolic": 130,
                "target_diastolic": 80,
            },
        ),
        actor_user_id=supervisor_user.id,
    )
    assert enrolment.id is not None
    assert enrolment.program_code == "DIABETES_T2"
    assert enrolment.status == "active"
    assert enrolment.patient_name == patient.full_name

    # 3. Single-Active-Enrolment Invariant: Duplicate active enrolment in same program MUST FAIL (409)
    with pytest.raises(HTTPException) as exc_dup:
        await enrol_patient(
            db,
            facility_id=facility.id,
            body=ProgramEnrolmentCreate(
                patient_id=patient.id,
                program_code="DIABETES_T2",
                target_outcomes={"target_hba1c": 7.0},
            ),
            actor_user_id=supervisor_user.id,
        )
    assert exc_dup.value.status_code == 409
    assert "already actively enrolled" in exc_dup.value.detail

    # 4. Enrolment into a different program (Hypertension) is allowed
    htn_enrolment = await enrol_patient(
        db,
        facility_id=facility.id,
        body=ProgramEnrolmentCreate(
            patient_id=patient.id,
            program_code="HYPERTENSION",
            target_outcomes={"target_systolic": 130, "target_diastolic": 80},
        ),
        actor_user_id=supervisor_user.id,
    )
    assert htn_enrolment.id is not None
    assert htn_enrolment.program_code == "HYPERTENSION"


async def test_hd28_record_program_encounters_trajectory_and_exit(db):
    facility, _, supervisor_user, surgeon_user, patient = await _setup_suite_7_env(db)

    enrolment = await enrol_patient(
        db,
        facility_id=facility.id,
        body=ProgramEnrolmentCreate(
            patient_id=patient.id,
            program_code="DIABETES_T2",
            target_outcomes={"target_hba1c": 7.0},
        ),
        actor_user_id=supervisor_user.id,
    )

    # 1. Record Follow-up Encounter 1
    today = date.today()
    enc1 = await record_program_visit(
        db,
        enrolment_id=enrolment.id,
        facility_id=facility.id,
        body=ProgramVisitCreate(
            scheduled_date=today - timedelta(days=90),
            completed_date=today - timedelta(days=90),
            metrics={"hba1c": 8.4, "bp_systolic": 142, "bp_diastolic": 90, "bmi": 28.5},
            clinical_summary="Baseline consultation. Metformin escalated to 1000mg BD. Dietary counselling given.",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert enc1.id is not None
    assert enc1.metrics["hba1c"] == 8.4

    # 2. Record Follow-up Encounter 2 (demonstrating clinical trajectory improvement)
    enc2 = await record_program_visit(
        db,
        enrolment_id=enrolment.id,
        facility_id=facility.id,
        body=ProgramVisitCreate(
            scheduled_date=today,
            completed_date=today,
            metrics={"hba1c": 6.8, "bp_systolic": 126, "bp_diastolic": 78, "bmi": 27.1},
            clinical_summary="Significant glycaemic control achieved. HbA1c reduced from 8.4% to 6.8%. Continue regimen.",
        ),
        actor_user_id=surgeon_user.id,
    )
    assert enc2.metrics["hba1c"] == 6.8

    # 3. Retrieve Timeline and verify visits
    timeline = await get_enrolment_timeline(db, enrolment_id=enrolment.id, facility_id=facility.id)
    assert len(timeline.visits) >= 2
    # Verify that the two recorded visits exist in timeline
    hba1c_vals = [v.metrics.get("hba1c") for v in timeline.visits if v.metrics]
    assert 8.4 in hba1c_vals
    assert 6.8 in hba1c_vals

    # 4. Program Exit (Outcome: completed/graduated)
    exited = await exit_enrolment(
        db,
        enrolment_id=enrolment.id,
        facility_id=facility.id,
        body=ProgramEnrolmentExitRequest(
            exit_date=today,
            exit_reason="Target glycaemic control sustained for 6 months, graduated to routine primary care",
        ),
        actor_user_id=supervisor_user.id,
    )
    assert exited.status == "exited"
    assert "graduated to routine primary care" in exited.exit_reason

    # 5. After exit, patient CAN be re-enrolled into DIABETES_T2 if clinically necessary
    re_enrol = await enrol_patient(
        db,
        facility_id=facility.id,
        body=ProgramEnrolmentCreate(
            patient_id=patient.id,
            program_code="DIABETES_T2",
            target_outcomes={"target_hba1c": 7.0},
        ),
        actor_user_id=supervisor_user.id,
    )
    assert re_enrol.id is not None
    assert re_enrol.status == "active"
