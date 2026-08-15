"""Tests for #201 (B3-W4-02): OPD note + prescription FHIR stubs wired
to encounter close."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_closing_visit_with_stored_note_creates_fhir_bundle(db, seed):
    from app.opd.models import Visit, Encounter
    from app.opd.service import transition_visit_status
    from app.patients.models import Patient
    from app.integrations.abdm.fhir.models import FhirBundleTransaction
    from app.outbox.models import OutboxEvent

    dept, room, doctor = seed
    facility_id = dept.facility_id

    patient = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260811-{uuid.uuid4().hex[:4]}",
        full_name="Test Patient",
        sex="male",
        age_years=35,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    db.add(patient)
    await db.flush()

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST01-260811-{uuid.uuid4().hex[:5]}",
        patient_id=patient.id,
        facility_id=facility_id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime.now(timezone.utc),
        created_by=doctor.id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=doctor.id,
        subjective="Patient reports headache",
        objective="BP 120/80, afebrile",
        assessment="Tension headache",
        plan="Paracetamol 500mg TDS",
        note_status="stored",
        created_by=doctor.id,
    )
    db.add(encounter)
    await db.flush()

    await transition_visit_status(
        db, visit=visit, target_status="closed", reason=None, updated_by=doctor.id
    )

    txns = (await db.execute(select(FhirBundleTransaction))).scalars().all()
    assert len(txns) == 1
    assert txns[0].bundle_id.startswith("BDL-NOTE-")
    assert txns[0].gateway_response_status == "stub_not_sent"
    assert txns[0].patient_id == patient.id
    assert txns[0].facility_id == facility_id

    events = (await db.execute(select(OutboxEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "opconsultrecord_bundle_built"
    assert events[0].payload["record_type"] == "OPConsultRecord"


@pytest.mark.asyncio
async def test_closing_visit_with_unstored_note_creates_no_bundle(db, seed):
    from app.opd.models import Visit, Encounter
    from app.opd.service import transition_visit_status
    from app.patients.models import Patient
    from app.integrations.abdm.fhir.models import FhirBundleTransaction

    dept, room, doctor = seed
    facility_id = dept.facility_id

    patient = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260811-{uuid.uuid4().hex[:4]}",
        full_name="Test Patient 2",
        sex="female",
        age_years=28,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    db.add(patient)
    await db.flush()

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST01-260811-{uuid.uuid4().hex[:5]}",
        patient_id=patient.id,
        facility_id=facility_id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime.now(timezone.utc),
        created_by=doctor.id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=doctor.id,
        note_status="pending",
        created_by=doctor.id,
    )
    db.add(encounter)
    await db.flush()

    await transition_visit_status(
        db, visit=visit, target_status="closed", reason=None, updated_by=doctor.id
    )

    txns = (await db.execute(select(FhirBundleTransaction))).scalars().all()
    assert len(txns) == 0


@pytest.mark.asyncio
async def test_closing_visit_with_prescription_creates_rx_bundle(db, seed):
    from app.opd.models import Visit, Encounter
    from app.opd.service import transition_visit_status
    from app.patients.models import Patient
    from app.orders.models import Prescription, PrescriptionItem
    from app.integrations.abdm.fhir.models import FhirBundleTransaction

    dept, room, doctor = seed
    facility_id = dept.facility_id

    patient = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260811-{uuid.uuid4().hex[:4]}",
        full_name="Test Patient 3",
        sex="male",
        age_years=50,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    db.add(patient)
    await db.flush()

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST01-260811-{uuid.uuid4().hex[:5]}",
        patient_id=patient.id,
        facility_id=facility_id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime.now(timezone.utc),
        created_by=doctor.id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=doctor.id,
        note_status="pending",
        created_by=doctor.id,
    )
    db.add(encounter)
    await db.flush()

    prescription = Prescription(
        id=uuid.uuid4(),
        encounter_id=encounter.id,
        facility_id=facility_id,
        patient_id=patient.id,
        created_by=doctor.id,
    )
    db.add(prescription)
    await db.flush()

    item = PrescriptionItem(
        id=uuid.uuid4(),
        prescription_id=prescription.id,
        medicine_name="Paracetamol",
        dosage="500mg",
        frequency="TDS",
        status="prescribed",
    )
    db.add(item)
    await db.flush()

    await transition_visit_status(
        db, visit=visit, target_status="closed", reason=None, updated_by=doctor.id
    )

    txns = (await db.execute(select(FhirBundleTransaction))).scalars().all()
    assert len(txns) == 1
    assert txns[0].bundle_id.startswith("BDL-RX-")


@pytest.mark.asyncio
async def test_encounter_close_never_blocks_visit_close_on_missing_data(db, seed):
    """An encounter with no note and no prescriptions still lets the
    visit close -- the FHIR stub step is best-effort per its own
    docstring."""
    from app.opd.models import Visit, Encounter
    from app.opd.service import transition_visit_status
    from app.patients.models import Patient

    dept, room, doctor = seed
    facility_id = dept.facility_id

    patient = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260811-{uuid.uuid4().hex[:4]}",
        full_name="Test Patient 4",
        sex="female",
        age_years=60,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    db.add(patient)
    await db.flush()

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST01-260811-{uuid.uuid4().hex[:5]}",
        patient_id=patient.id,
        facility_id=facility_id,
        visit_type="opd",
        status="in_consultation",
        visit_date=datetime.now(timezone.utc),
        created_by=doctor.id,
    )
    db.add(visit)
    await db.flush()

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit.id,
        facility_id=facility_id,
        provider_user_id=doctor.id,
        note_status="pending",
        created_by=doctor.id,
    )
    db.add(encounter)
    await db.flush()

    result = await transition_visit_status(
        db, visit=visit, target_status="closed", reason=None, updated_by=doctor.id
    )
    assert result.status == "closed"
