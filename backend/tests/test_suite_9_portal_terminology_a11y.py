"""Comprehensive test suite for Suite 9 (HD-33 to HD-36).

Covers:
- HD-33: Patient Portal Released Documents (Prescriptions, Lab, Radiology, Discharge, Vaccines)
- HD-34: Clinical Terminology Search (ICD-10, ICD-11, SNOMED CT) & Specialty Encounters (Pediatric, Cardiology, Obstetrics)
- HD-36: ABDM M1 Scan-and-Share Reception Ticket Flow & Check-in
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.admissions.models import Admission, Bed, Discharge, Ward
from app.auth.deps import DbUser
from app.consent.models import DataAccessLog
from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.integrations.abdm.models import ScanShareTicket
from app.integrations.abdm.scan_share_router import (
    ScanShareCheckInPayload,
    check_in_scan_share_ticket,
    get_scan_share_ticket,
    list_scan_share_tickets,
)
from app.opd.models import Encounter, Visit
from app.orders.models import Order, Prescription, PrescriptionItem
from app.pathology.models import LabOrderItem, LabResult
from app.patients.models import Patient, PatientPortalBinding
from app.patients.portal_self_router import (
    get_my_document_detail,
    get_my_documents,
)
from app.radiology.models import RadiologyOrderItem, RadiologyReport
from app.terminology.router import (
    get_encounter_specialty_assessments,
    get_specialty_template,
    list_specialty_templates,
    record_encounter_specialty_assessment,
    search_clinical_terms,
)
from app.terminology.schemas import SpecialtyEncounterCreate
from app.users.models import Facility, User


@pytest.fixture
async def suite_9_seed(db, seed):
    """Seed test facility, users, and bound patient for Suite 9 testing."""
    department, _room, staff_user = seed
    facility_id = department.facility_id

    # Create bound patient
    patient = Patient(
        id=uuid.uuid4(),
        uhid="IN-DL-AIIMS-2026-009988-X",
        full_name="Ananya Sharma",
        sex="female",
        dob=date(1994, 6, 15),
        age_years=32,
        mobile="+919876543210",
        identity_path="abdm",
        status="active",
        facility_id=facility_id,
        created_by=staff_user.id,
    )
    binding = PatientPortalBinding(
        id=uuid.uuid4(),
        user_id=staff_user.id,
        patient_id=patient.id,
        facility_id=facility_id,
        verification_method="abha_otp",
        verification_reference="OTP-TEST-SUITE-9",
        verified_by=staff_user.id,
    )
    db.add_all([patient, binding])
    await db.flush()

    patient_caller = DbUser(
        id=staff_user.id,
        keycloak_sub=staff_user.keycloak_sub,
        username="ananya_patient",
        facility_id=facility_id,
        roles=["patient"],
    )

    clinician_caller = DbUser(
        id=staff_user.id,
        keycloak_sub=staff_user.keycloak_sub,
        username="dr_sharma",
        facility_id=facility_id,
        roles=["doctor"],
    )

    receptionist_caller = DbUser(
        id=staff_user.id,
        keycloak_sub=staff_user.keycloak_sub,
        username="receptionist_1",
        facility_id=facility_id,
        roles=["receptionist"],
    )

    return {
        "facility_id": facility_id,
        "department": department,
        "staff_user": staff_user,
        "patient": patient,
        "binding": binding,
        "patient_caller": patient_caller,
        "clinician_caller": clinician_caller,
        "receptionist_caller": receptionist_caller,
    }


# ============================================================================
# 1. HD-33: PATIENT PORTAL RELEASED DOCUMENTS TESTS
# ============================================================================

async def test_patient_portal_released_documents_query_and_details(db, suite_9_seed):
    ctx = suite_9_seed
    patient = ctx["patient"]
    binding = ctx["binding"]
    caller = ctx["patient_caller"]
    facility_id = ctx["facility_id"]
    user_id = ctx["staff_user"].id

    # 1. Seed Visit and Encounter
    visit = Visit(
        id=uuid.uuid4(),
        visit_number="VIS-2026-9001",
        patient_id=patient.id,
        facility_id=facility_id,
        department_id=ctx["department"].id,
        visit_type="opd",
        status="closed",
        visit_date=datetime.now(UTC),
        created_by=user_id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=user_id,
        encounter_type="consultation",
        chief_complaint="Chest pain and palpitations",
        started_at=datetime.now(UTC) - timedelta(days=2),
        ended_at=datetime.now(UTC) - timedelta(days=1),
        created_by=user_id,
    )
    db.add(encounter)
    await db.flush()

    # 2. Seed Released Prescription
    rx = Prescription(
        id=uuid.uuid4(),
        encounter_id=encounter.id,
        facility_id=facility_id,
        patient_id=patient.id,
        notes="Take medication after meals.",
        created_by=user_id,
    )
    db.add(rx)
    await db.flush()

    rx_item1 = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=rx.id,
        medicine_name="Amlodipine 5mg",
        dosage="1 tablet",
        frequency="Once daily",
    )
    rx_item2 = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=rx.id,
        medicine_name="Atorvastatin 20mg",
        dosage="1 tablet",
        frequency="At bedtime",
    )
    db.add_all([rx_item1, rx_item2])

    # 3. Seed Released Lab Report
    order_lab = Order(
        id=uuid.uuid4(),
        order_number="ORD-LAB-9001",
        encounter_id=encounter.id,
        facility_id=facility_id,
        patient_id=patient.id,
        order_type="lab",
        priority="routine",
        status="completed",
        ordered_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        completed_by=user_id,
        created_by=user_id,
    )
    db.add(order_lab)
    await db.flush()

    lab_item = LabOrderItem(
        id=uuid.uuid4(),
        order_id=order_lab.id,
        accession_number="ACC-L-9001",
        test_code="LIPID",
        test_name="Lipid Profile Panel",
        sample_type="serum",
        status="released",
        created_by=user_id,
    )
    db.add(lab_item)
    await db.flush()

    lab_result = LabResult(
        id=uuid.uuid4(),
        lab_order_item_id=lab_item.id,
        version=1,
        is_current=True,
        status="final",
        result_data={"total_cholesterol": 195, "hdl": 48, "ldl": 120, "triglycerides": 140},
        created_by=user_id,
    )
    db.add(lab_result)

    # 4. Seed Released Radiology Report
    order_rad = Order(
        id=uuid.uuid4(),
        order_number="ORD-RAD-9001",
        encounter_id=encounter.id,
        facility_id=facility_id,
        patient_id=patient.id,
        order_type="radiology",
        priority="routine",
        status="completed",
        ordered_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        completed_by=user_id,
        created_by=user_id,
    )
    db.add(order_rad)
    await db.flush()

    rad_item = RadiologyOrderItem(
        id=uuid.uuid4(),
        order_id=order_rad.id,
        accession_number="ACC-R-9001",
        modality="xray",
        scan_type="Chest PA View",
        status="scanned",
        created_by=user_id,
    )
    db.add(rad_item)
    await db.flush()

    rad_report = RadiologyReport(
        id=uuid.uuid4(),
        radiology_order_item_id=rad_item.id,
        version=1,
        is_current=True,
        findings="Cardiothoracic ratio normal. Clear lung fields. No focal consolidation.",
        impression="Normal chest radiograph. No acute cardiopulmonary pathology.",
        status="signed",
        created_by=user_id,
    )
    db.add(rad_report)

    # 5. Seed Inpatient Discharge Summary
    ward = Ward(id=uuid.uuid4(), name="Cardiology Ward A", facility_id=facility_id)
    db.add(ward)
    await db.flush()
    bed = Bed(id=uuid.uuid4(), ward_id=ward.id, bed_number="CARD-01", status="vacant")
    db.add(bed)
    await db.flush()

    admission = Admission(
        id=uuid.uuid4(),
        visit_id=visit.id,
        patient_id=patient.id,
        ward_id=ward.id,
        bed_id=bed.id,
        admitted_at=datetime.now(UTC) - timedelta(days=10),
        status="discharged",
        created_by=user_id,
    )
    db.add(admission)
    await db.flush()

    discharge = Discharge(
        id=uuid.uuid4(),
        admission_id=admission.id,
        discharged_at=datetime.now(UTC) - timedelta(days=7),
        discharge_type="discharged",
        discharge_summary="Patient admitted for chest pain evaluation. Angiogram normal. Hemodynamically stable.",
        follow_up_date=date(2026, 10, 1),
        created_by=user_id,
    )
    db.add(discharge)

    # 6. Seed Immunization Certificate
    vaccine = VaccineCatalogue(
        id=uuid.uuid4(),
        code="HEPB-01",
        name="Hepatitis B Recombinant",
        target_disease="Hepatitis B",
        standard_doses=3,
        min_age_days=0,
        route="intramuscular",
        site="deltoid",
        dose_quantity="1.0 ml",
        is_active=True,
    )
    db.add(vaccine)
    await db.flush()

    immunization = ImmunizationRecord(
        id=uuid.uuid4(),
        patient_id=patient.id,
        vaccine_id=vaccine.id,
        vaccine_code="HEPB-01",
        dose_number=1,
        administered_at=datetime.now(UTC) - timedelta(days=30),
        batch_number="BATCH-HB-2026",
        expiry_date=date(2027, 12, 31),
        manufacturer="Serum Institute",
        administered_by=user_id,
    )
    db.add(immunization)
    await db.flush()

    # TEST: GET /documents (All categories)
    all_docs = await get_my_documents(binding, caller, db, category=None, limit=50, offset=0)
    assert all_docs.total == 5
    types_found = {d.document_type for d in all_docs.items}
    assert types_found == {"prescription", "lab_report", "radiology", "discharge_summary", "vaccine"}

    # Verify chronological ordering (most recent first)
    def _norm(dt):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    dates = [_norm(d.date) for d in all_docs.items]
    assert dates == sorted(dates, reverse=True)

    # TEST: Category Filtering
    rx_only = await get_my_documents(binding, caller, db, category="prescription", limit=10, offset=0)
    assert rx_only.total == 1
    assert rx_only.items[0].document_type == "prescription"
    assert "Amlodipine" in rx_only.items[0].summary

    lab_only = await get_my_documents(binding, caller, db, category="lab_report", limit=10, offset=0)
    assert lab_only.total == 1
    assert "Lipid Profile" in lab_only.items[0].title

    rad_only = await get_my_documents(binding, caller, db, category="radiology", limit=10, offset=0)
    assert rad_only.total == 1
    assert rad_only.items[0].document_type == "radiology"
    assert "Chest PA" in rad_only.items[0].title

    # TEST: Pagination
    paginated = await get_my_documents(binding, caller, db, category=None, limit=2, offset=0)
    assert len(paginated.items) == 2
    assert paginated.total == 5

    # TEST: Detail View for Prescription
    rx_detail = await get_my_document_detail(
        doc_type="prescription",
        doc_id=rx.id,
        binding=binding,
        current_user=caller,
        db=db,
    )
    assert rx_detail.document_type == "prescription"
    assert rx_detail.patient_uhid == patient.uhid
    assert rx_detail.patient_name == patient.full_name
    assert len(rx_detail.content["items"]) == 2

    # TEST: Detail View for Lab Report
    lab_detail = await get_my_document_detail(
        doc_type="lab_report",
        doc_id=lab_item.id,
        binding=binding,
        current_user=caller,
        db=db,
    )
    assert lab_detail.document_type == "lab_report"
    assert lab_detail.content["accession_number"] == "ACC-L-9001"
    assert lab_detail.content["result_data"]["total_cholesterol"] == 195

    # TEST: Detail View for Radiology Report
    rad_detail = await get_my_document_detail(
        doc_type="radiology",
        doc_id=rad_item.id,
        binding=binding,
        current_user=caller,
        db=db,
    )
    assert rad_detail.document_type == "radiology"
    assert "Normal chest" in rad_detail.content["impression"]

    # TEST: Detail View for Vaccine
    vac_detail = await get_my_document_detail(
        doc_type="vaccine",
        doc_id=immunization.id,
        binding=binding,
        current_user=caller,
        db=db,
    )
    assert vac_detail.document_type == "vaccine"
    assert vac_detail.content["vaccine_name"] == "Hepatitis B Recombinant"
    assert vac_detail.content["batch_number"] == "BATCH-HB-2026"

    # TEST: Audit Log Verification
    audit_logs = (
        await db.execute(
            select(DataAccessLog).where(DataAccessLog.patient_id == patient.id)
        )
    ).scalars().all()
    logged_resources = {entry.resource_type for entry in audit_logs}
    assert "clinical_documents" in logged_resources
    assert "clinical_document_prescription" in logged_resources


# ============================================================================
# 2. HD-34: CLINICAL TERMINOLOGY & SPECIALTY DEPTH TESTS
# ============================================================================

async def test_terminology_search_multi_coding():
    # 1. Search for hypertension across all systems
    results_all = await search_clinical_terms(q="hypertension", system="all", limit=20)
    assert len(results_all) >= 3
    systems = {r.system for r in results_all}
    assert "icd10" in systems
    assert "icd11" in systems
    assert "snomed" in systems

    # Check ICD-10 code for Essential hypertension
    icd10_res = [r for r in results_all if r.system == "icd10"]
    assert any("I10" in r.code for r in icd10_res)

    # 2. Filter specifically by snomed
    snomed_res = await search_clinical_terms(q="diabetes", system="snomed", limit=10)
    assert len(snomed_res) > 0
    assert all(r.system == "snomed" for r in snomed_res)

    # 3. Filter by icd11
    icd11_res = await search_clinical_terms(q="malaria", system="icd11", limit=10)
    assert len(icd11_res) > 0
    assert all(r.system == "icd11" for r in icd11_res)


async def test_specialty_templates_and_encounter_recording(db, suite_9_seed):
    ctx = suite_9_seed
    patient = ctx["patient"]
    facility_id = ctx["facility_id"]
    clinician = ctx["clinician_caller"]
    user_id = ctx["staff_user"].id

    # 1. Check template definitions
    templates = await list_specialty_templates()
    template_types = {t.specialty_type for t in templates}
    assert {"pediatric", "cardiology", "obstetrics"}.issubset(template_types)

    ped_template = await get_specialty_template(specialty_type="pediatric")
    assert ped_template.title == "Pediatric Clinical Evaluation"
    field_names = [
        field.name
        for section in ped_template.sections
        for field in section.fields
    ]
    assert "birth_weight_kg" in field_names
    assert "head_circumference_cm" in field_names
    assert "gross_motor_status" in field_names

    cardio_template = await get_specialty_template(specialty_type="cardiology")
    cardio_fields = [
        field.name
        for section in cardio_template.sections
        for field in section.fields
    ]
    assert "nyha_class" in cardio_fields
    assert "lvef_percent" in cardio_fields

    ob_template = await get_specialty_template(specialty_type="obstetrics")
    ob_fields = [
        field.name
        for section in ob_template.sections
        for field in section.fields
    ]
    assert "gravida" in ob_fields
    assert "fundal_height_cm" in ob_fields
    assert "fetal_heart_rate_bpm" in ob_fields

    # 2. Seed Visit and Encounter
    visit = Visit(
        id=uuid.uuid4(),
        visit_number="VIS-2026-SPEC-01",
        patient_id=patient.id,
        facility_id=facility_id,
        department_id=ctx["department"].id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime.now(UTC),
        created_by=user_id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=user_id,
        encounter_type="consultation",
        created_by=user_id,
    )
    db.add(encounter)
    await db.flush()

    # 3. Record Pediatric Specialty Assessment
    ped_payload = SpecialtyEncounterCreate(
        specialty_type="pediatric",
        clinical_data={
            "birth_weight_kg": 3.2,
            "gestational_age_weeks": 39,
            "delivery_mode": "normal_vaginal",
            "head_circumference_cm": 44.5,
            "muac_cm": 14.2,
            "gross_motor_status": "age_appropriate",
            "immunization_up_to_date": True,
        },
    )
    record = await record_encounter_specialty_assessment(
        encounter_id=encounter.id,
        payload=ped_payload,
        current_user=clinician,
        db=db,
    )
    assert record.specialty_type == "pediatric"
    assert record.clinical_data["birth_weight_kg"] == 3.2
    assert record.patient_id == patient.id

    # 4. Retrieve Specialty Encounters
    records = await get_encounter_specialty_assessments(
        encounter_id=encounter.id,
        current_user=clinician,
        db=db,
    )
    assert len(records) == 1
    assert records[0].clinical_data["head_circumference_cm"] == 44.5

    # 5. Update Existing Specialty Record (Idempotent update)
    ped_payload_updated = SpecialtyEncounterCreate(
        specialty_type="pediatric",
        clinical_data={
            "birth_weight_kg": 3.2,
            "gestational_age_weeks": 39,
            "head_circumference_cm": 45.0,  # updated
            "gross_motor_status": "age_appropriate",
        },
    )
    updated_rec = await record_encounter_specialty_assessment(
        encounter_id=encounter.id,
        payload=ped_payload_updated,
        current_user=clinician,
        db=db,
    )
    assert updated_rec.id == record.id
    assert updated_rec.clinical_data["head_circumference_cm"] == 45.0


# ============================================================================
# 3. HD-36: ABDM M1 SCAN-AND-SHARE RECEPTION TICKET FLOW TESTS
# ============================================================================

async def test_abdm_m1_scan_and_share_reception_ticket_flow(db, suite_9_seed):
    ctx = suite_9_seed
    facility_id = ctx["facility_id"]
    patient = ctx["patient"]
    receptionist = ctx["receptionist_caller"]

    # 1. Create active ScanShareTicket
    ticket = ScanShareTicket(
        id=uuid.uuid4(),
        facility_id=facility_id,
        token_number="009988",
        abha_address="ananya@abdm",
        profile_data={
            "full_name": patient.full_name,
            "gender": patient.sex,
            "mobile": patient.mobile,
            "abha_number": "14-1234-5678-9012",
        },
        status="active",
        counter=None,
        patient_id=patient.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(ticket)
    await db.flush()

    # 2. Receptionist lists active tickets
    active_tickets = await list_scan_share_tickets(
        current_user=receptionist,
        db=db,
        status="active",
        limit=50,
    )
    assert any(t.token_number == "009988" for t in active_tickets)
    matching_ticket = next(t for t in active_tickets if t.token_number == "009988")
    assert matching_ticket.patient_name == "Ananya Sharma"
    assert matching_ticket.abha_address == "ananya@abdm"

    # 3. Receptionist looks up ticket by token number
    fetched_ticket = await get_scan_share_ticket(
        token_number="009988",
        current_user=receptionist,
        db=db,
    )
    assert fetched_ticket.token_number == "009988"
    assert fetched_ticket.patient_uhid == patient.uhid

    # 4. Check-in at reception desk
    check_in_resp = await check_in_scan_share_ticket(
        token_number="009988",
        payload=ScanShareCheckInPayload(counter="Counter 4"),
        current_user=receptionist,
        db=db,
    )
    assert check_in_resp.counter == "Counter 4"
    assert check_in_resp.token_number == "009988"
    assert check_in_resp.slip_barcode_data == str(ticket.id)
    assert check_in_resp.check_in_time is not None

    # 5. Verify status updated in database
    refreshed_ticket = await db.get(ScanShareTicket, ticket.id)
    assert refreshed_ticket.status == "checked_in"
    assert refreshed_ticket.counter == "Counter 4"
