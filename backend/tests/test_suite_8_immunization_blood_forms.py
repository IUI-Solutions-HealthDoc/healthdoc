"""Automated test suite for Suite 8 (HD-29 to HD-32).

Covers:
- HD-29: Immunization Lifecycle (Catalogue, Due List Schedule, Administration, Certificate)
- HD-29: Blood Bank Lifecycle (Donor Screening, Unit Collection, Crossmatch, Controlled Issue)
- HD-30: Configurable Forms, Form Submissions, Clinical Order Sets, and CSV Administration
- HD-31: Transactional Outbox Dead-Letter Queue (DLQ), Payload Redaction, Replay, Metrics
- HD-32: Walk-in Laboratory & Pharmacy Direct Service Journeys (VisitType.DIRECT_SERVICE)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.deps import DbUser
from app.blood_bank.models import BloodCrossmatch, BloodDonor, BloodUnit
from app.blood_bank.schemas import (
    BloodCrossmatchCreate,
    BloodDonorCreate,
    BloodIssueRequest,
    BloodUnitCreate,
)
from app.blood_bank.service import (
    compute_donor_eligibility,
    create_crossmatch,
    create_donor,
    create_unit,
    issue_blood,
    list_donors,
    list_units,
)
from app.common.enums import VisitType
from app.forms.models import ClinicalOrderSet, FormDefinition, FormSubmission
from app.forms.schemas import (
    ApplyOrderSetRequest,
    ClinicalOrderSetCreate,
    FormDefinitionCreate,
    FormSubmissionCreate,
)
from app.forms.service import (
    apply_order_set,
    create_form_definition,
    create_submission,
    ensure_defaults_seeded,
    export_csv,
    import_csv,
    list_form_definitions,
    list_order_sets,
    list_patient_submissions,
    sanitize_csv_cell,
    validate_csv,
)
from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.immunization.schemas import ImmunizationRecordCreate
from app.immunization.service import (
    ensure_catalogue_seeded,
    generate_certificate,
    get_catalogue,
    get_patient_schedule,
    record_administration,
)
from app.opd.models import Visit
from app.opd.schemas import VisitCreate
from app.opd.service import create_visit
from app.outbox.models import OutboxDeadLetter, OutboxEvent
from app.outbox.service import (
    enqueue,
    get_metrics,
    list_dead_letters,
    list_events,
    redact_payload,
    replay_dead_letter,
)
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _setup_suite_8_fixture(db):
    facility = Facility(
        id=uuid.uuid4(),
        name="Apex Multi-Speciality Hospital",
        code=f"APX{uuid.uuid4().hex[:4].upper()}",
        state_code="MH",
    )
    db.add(facility)

    staff = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_staff_{uuid.uuid4().hex[:6]}",
        username=f"staff_{uuid.uuid4().hex[:6]}",
        full_name="Nurse Shweta",
        is_active=True,
    )
    db.add(staff)
    await db.flush()

    patient_child = Patient(
        id=uuid.uuid4(),
        facility_id=facility.id,
        uhid=f"UHID-CHLD-{uuid.uuid4().hex[:6].upper()}",
        full_name="Aarav Sharma",
        sex="male",
        dob=date.today() - timedelta(days=60),  # 2 months old child
        status="active",
        identity_path="demographics_only",
        created_by=staff.id,
    )
    db.add(patient_child)

    patient_adult = Patient(
        id=uuid.uuid4(),
        facility_id=facility.id,
        uhid=f"UHID-ADLT-{uuid.uuid4().hex[:6].upper()}",
        full_name="Vikram Seth",
        sex="male",
        dob=date.today() - timedelta(days=365 * 35),  # 35 years old
        status="active",
        identity_path="demographics_only",
        created_by=staff.id,
    )
    db.add(patient_adult)
    await db.flush()

    return facility, staff, patient_child, patient_adult


# ==============================================================================
# 1. HD-29: IMMUNIZATION LIFECYCLE
# ==============================================================================

async def test_immunization_catalogue_and_patient_due_schedule(db):
    facility, staff, child, adult = await _setup_suite_8_fixture(db)

    # 1. Seed & fetch catalogue
    catalogue = await get_catalogue(db)
    assert len(catalogue) >= 8
    codes = {v.code for v in catalogue}
    assert "BCG" in codes
    assert "PENTAVALENT-1" in codes

    # 2. Schedule for 60-day child: Pentavalent-1 (min_age 42 days) should be DUE/OVERDUE
    schedule = await get_patient_schedule(db, child.id)
    assert schedule.patient_name == "Aarav Sharma"
    assert len(schedule.administered) == 0
    assert len(schedule.due) > 0

    penta_due = next((item for item in schedule.due if item.vaccine_code == "PENTAVALENT-1"), None)
    assert penta_due is not None
    assert penta_due.status in ("due", "overdue")

    # 3. Administer Pentavalent-1
    record_payload = ImmunizationRecordCreate(
        patient_id=child.id,
        vaccine_code="PENTAVALENT-1",
        dose_number=1,
        batch_number="BATCH-PENTA-9921",
        expiry_date=date.today() + timedelta(days=365),
        manufacturer="Serum Institute of India",
        site="anterolateral_thigh",
        route="intramuscular",
    )
    recorded = await record_administration(db, record_payload, staff.id)
    assert recorded.vaccine_code == "PENTAVALENT-1"
    assert recorded.batch_number == "BATCH-PENTA-9921"
    assert recorded.dose_number == 1

    # 4. Schedule re-check: Pentavalent-1 now in administered and not in due
    updated_schedule = await get_patient_schedule(db, child.id)
    assert len(updated_schedule.administered) == 1
    assert updated_schedule.administered[0].vaccine_code == "PENTAVALENT-1"
    assert not any(item.vaccine_code == "PENTAVALENT-1" for item in updated_schedule.due)

    # 5. Printable Certificate
    cert = await generate_certificate(db, child.id, facility.id)
    assert cert.patient_name == "Aarav Sharma"
    assert cert.facility_name == facility.name
    assert cert.certificate_id.startswith("IMM-CERT-")
    assert len(cert.records) == 1
    assert cert.records[0].batch_number == "BATCH-PENTA-9921"


# ==============================================================================
# 2. HD-29: BLOOD BANK LIFECYCLE
# ==============================================================================

async def test_blood_donor_screening_and_eligibility(db):
    facility, staff, _, _ = await _setup_suite_8_fixture(db)

    # 1. Eligible donor (weight 65, Hb 14.2, first donation)
    d1 = await create_donor(
        db,
        BloodDonorCreate(
            full_name="Rohan Mehra",
            blood_group="O+",
            weight_kg=65.0,
            hemoglobin_g_dl=14.2,
            mobile="9876543210",
        ),
        staff.id,
    )
    assert d1.is_eligible is True

    # 2. Ineligible donor due to low hemoglobin (< 12.5)
    d2 = await create_donor(
        db,
        BloodDonorCreate(
            full_name="Anil Anemic",
            blood_group="A+",
            weight_kg=60.0,
            hemoglobin_g_dl=11.2,
        ),
        staff.id,
    )
    assert d2.is_eligible is False

    # 3. Ineligible donor due to recent donation (< 90 days)
    d3 = await create_donor(
        db,
        BloodDonorCreate(
            full_name="Karan Frequent",
            blood_group="B+",
            weight_kg=70.0,
            hemoglobin_g_dl=15.0,
            last_donation_date=date.today() - timedelta(days=30),
        ),
        staff.id,
    )
    assert d3.is_eligible is False

    # 4. List donors filtering by eligibility
    eligible_donors = await list_donors(db, facility.id, is_eligible=True)
    assert any(d.id == d1.id for d in eligible_donors)
    assert not any(d.id == d2.id for d in eligible_donors)


async def test_blood_unit_crossmatch_and_controlled_issue(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)

    donor = await create_donor(
        db,
        BloodDonorCreate(
            full_name="Sanjay Donor",
            blood_group="B+",
            weight_kg=72.0,
            hemoglobin_g_dl=14.8,
        ),
        staff.id,
    )

    # 1. Collect and screen blood unit
    unit = await create_unit(
        db,
        BloodUnitCreate(
            donor_id=donor.id,
            bag_number=f"BAG-{uuid.uuid4().hex[:6].upper()}",
            blood_group="B+",
            volume_ml=450,
            expiry_date=date.today() + timedelta(days=35),
            screening_status="passed",
        ),
        staff.id,
    )
    assert unit.status == "available"

    # 2. Perform crossmatch test
    xm = await create_crossmatch(
        db,
        BloodCrossmatchCreate(
            patient_id=adult.id,
            unit_id=unit.id,
            compatibility_result="compatible",
            notes="Major and minor compatibility verified without agglutination",
        ),
        staff.id,
    )
    assert xm.compatibility_result == "compatible"
    assert xm.issued_at is None

    # 3. Issue blood unit for transfusion
    issued_xm = await issue_blood(
        db,
        BloodIssueRequest(
            crossmatch_id=xm.id,
            notes="Issued to Ward 3 bed 12 for planned surgical transfusion",
        ),
        staff.id,
    )
    assert issued_xm.issued_at is not None

    # 4. Verify unit status transitioned to 'issued'
    unit_rows = await list_units(db, facility.id, status="issued")
    assert any(u.id == unit.id for u in unit_rows)

    # 5. Safety Invariant: Cannot issue the same unit twice
    with pytest.raises(ValueError, match="already been issued"):
        await issue_blood(db, BloodIssueRequest(crossmatch_id=xm.id), staff.id)


# ==============================================================================
# 3. HD-30: CONFIGURABLE FORMS & ORDER SETS
# ==============================================================================

async def test_dynamic_forms_and_submissions(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)
    await ensure_defaults_seeded(db, staff.id)

    # 1. List seeded definitions
    defs = await list_form_definitions(db)
    assert len(defs) >= 2
    codes = {d.code for d in defs}
    assert "SURGICAL_PRE_OP" in codes
    assert "DIABETES_MANAGEMENT" in codes

    pre_op_form = next(d for d in defs if d.code == "SURGICAL_PRE_OP")

    # 2. Submit responses with missing required field -> Raises ValueError
    with pytest.raises(ValueError, match="Missing required field"):
        await create_submission(
            db,
            FormSubmissionCreate(
                patient_id=adult.id,
                form_id=pre_op_form.id,
                form_data={"airway_mallampati": "I"},  # missing npo_hours, consent_signed
            ),
            staff.id,
        )

    # 3. Valid submission
    sub = await create_submission(
        db,
        FormSubmissionCreate(
            patient_id=adult.id,
            form_id=pre_op_form.id,
            form_data={
                "npo_hours": 8,
                "airway_mallampati": "II",
                "consent_signed": True,
                "pac_fitness": "Fit for general anesthesia ASA Grade 1",
            },
        ),
        staff.id,
    )
    assert sub.patient_id == adult.id
    assert sub.form_data["npo_hours"] == 8

    # 4. Patient history of submissions
    patient_subs = await list_patient_submissions(db, adult.id)
    assert len(patient_subs) >= 1
    assert patient_subs[0].id == sub.id


async def test_clinical_order_sets_protocol_application(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)
    await ensure_defaults_seeded(db, staff.id)

    # 1. List order sets
    order_sets = await list_order_sets(db)
    assert len(order_sets) >= 3
    codes = {o.code for o in order_sets}
    assert "SEPSIS_BUNDLE" in codes

    # 2. Create mock visit
    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST-{uuid.uuid4().hex[:6].upper()}",
        patient_id=adult.id,
        facility_id=facility.id,
        visit_type=VisitType.EMERGENCY.value,
        status="registered",
        visit_date=datetime.now(timezone.utc),
        created_by=staff.id,
    )
    db.add(visit)
    await db.flush()

    # The old implementation returned success without writing any orders.
    with pytest.raises(HTTPException) as exc:
        await apply_order_set(db, "SEPSIS_BUNDLE", adult.id, visit.id, staff.id)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "order_set_execution_unavailable"


# ==============================================================================
# 4. HD-30: CSV ADMINISTRATION & FORMULA INJECTION DEFENSE
# ==============================================================================

async def test_csv_validation_formula_injection_defense_and_import(db):
    facility, staff, _, _ = await _setup_suite_8_fixture(db)

    # 1. Malicious CSV with spreadsheet formula injection
    malicious_csv = """code,name,target_disease,standard_doses,min_age_days,route,site,dose_quantity
=cmd|' /C calc'!A0,Dangerous Calc Vaccine,Malware,1,0,oral,oral,1 drop
+12345,Plus Injection,Exploit,1,0,im,arm,0.5ml
@SUM(1+1),Formula Injection,Test,1,0,im,arm,0.5ml
VAC-SAFE-1,Safe Hepatitis Vaccine,Hepatitis,2,30,intramuscular,left_upper_arm,0.5 ml
"""
    val = validate_csv(malicious_csv, "vaccines")
    assert val.valid is False
    assert val.row_count == 4
    # Warnings flagged for formula prefixes
    assert len(val.warnings) >= 3

    # 2. Safe import strips malicious formula command characters
    with pytest.raises(ValueError):
        await import_csv(malicious_csv, "vaccines", db, staff.id)
    safe_csv = malicious_csv.splitlines()[0] + "\n" + malicious_csv.splitlines()[-1]
    res = await import_csv(safe_csv, "vaccines", db, staff.id)
    assert res.imported_count == 1
    stored = (await db.execute(select(VaccineCatalogue).where(VaccineCatalogue.code == "VAC-SAFE-1"))).scalar_one()
    assert stored.standard_doses == 2

    # 3. Verify sanitize_csv_cell escapes formulas with single quote prefix
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("@HYPERLINK(...)") == "'@HYPERLINK(...)"
    assert sanitize_csv_cell("Safe Text") == "Safe Text"

    # 4. Export CSV
    exported = await export_csv("vaccines", db)
    assert "code,name,target_disease" in exported


# ==============================================================================
# 5. HD-31: SAFE TRANSACTIONAL OUTBOX & DEAD-LETTER QUEUE
# ==============================================================================

async def test_outbox_dlq_redaction_replay_and_metrics(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)

    # 1. Enqueue outbox event
    await enqueue(
        db,
        aggregate_type="patient",
        aggregate_id=str(adult.id),
        event_type="registered",
        payload={"uhid": adult.uhid, "patient_name": adult.full_name},
    )
    await db.commit()

    events = await list_events(db, aggregate_type="patient")
    assert len(events) >= 1

    # 2. Redact sensitive clinical payload
    raw_payload = {
        "user_id": str(staff.id),
        "auth_token": "secret_bearer_token_12345",
        "aadhaar_number": "1234-5678-9012",
        "diagnosis": "Hypertension",
    }
    redacted = redact_payload(raw_payload)
    assert redacted["auth_token"] == "[REDACTED]"
    assert redacted["aadhaar_number"] == "[REDACTED]"
    assert redacted["diagnosis"] == "Hypertension"

    # 3. Simulate DLQ entry
    dl = OutboxDeadLetter(
        id=uuid.uuid4(),
        original_event_id=events[0].id,
        aggregate_type="patient",
        aggregate_id=adult.id,
        event_type="cloud_sync",
        payload_redacted=redacted,
        error_message="Gateway connection timeout after 5 attempts",
    )
    db.add(dl)
    await db.commit()
    await db.refresh(dl)

    dls = await list_dead_letters(db)
    assert any(str(d.id) == str(dl.id) for d in dls)

    # 4. Replay dead letter event
    replayed = await replay_dead_letter(db, str(dl.id))
    assert replayed.status == "pending"
    assert replayed.attempts == 0

    # 5. Check outbox metrics
    metrics = await get_metrics(db)
    assert metrics["total_events"] >= 1
    assert metrics["dead_letter_count"] >= 1


# ==============================================================================
# 6. HD-32: DIRECT SERVICE WALK-IN ENCOUNTERS
# ==============================================================================

async def test_walkin_direct_service_visit_journey(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)

    # 1. Verify VisitType enum contains DIRECT_SERVICE
    assert VisitType.DIRECT_SERVICE.value == "direct_service"
    # Direct service visits do NOT occupy a ward bed
    assert VisitType.DIRECT_SERVICE.value not in VisitType.bed_occupying()
    # Direct service visits do NOT take an OPD waiting queue counter token
    assert VisitType.DIRECT_SERVICE.value not in VisitType.token_issuing()

    # 2. Create a walk-in direct service visit
    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-DIR-{uuid.uuid4().hex[:6].upper()}",
        patient_id=adult.id,
        facility_id=facility.id,
        visit_type=VisitType.DIRECT_SERVICE.value,
        status="registered",
        visit_date=datetime.now(timezone.utc),
        created_by=staff.id,
    )
    db.add(visit)
    await db.flush()

    assert visit.visit_type == "direct_service"
    assert visit.status == "registered"

    # Query visit
    v_res = await db.execute(select(Visit).where(Visit.id == visit.id))
    retrieved = v_res.scalar_one_or_none()
    assert retrieved is not None
    assert retrieved.visit_type == "direct_service"
