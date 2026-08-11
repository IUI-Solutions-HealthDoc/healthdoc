"""backend/tests/test_encounters.py -- #180: encounter CRUD + diagnosis create/list."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.opd.models import Visit
from app.patients.models import Patient
from app.encounters import service
from app.encounters.schemas import DiagnosisCreate, EncounterCreate, EncounterUpdate


@pytest.fixture
async def visit(db, seed):
    dept, room, doctor = seed
    patient = Patient(id=uuid.uuid4(), uhid=f"UH{uuid.uuid4().hex[:8]}", facility_id=dept.facility_id,
                       full_name="Test Patient", sex="female", age_years=30,
                       identity_path="demographics_only", created_by=doctor.id)
    db.add(patient)
    await db.flush()
    v = Visit(id=uuid.uuid4(), visit_number=f"V{uuid.uuid4().hex[:8]}", patient_id=patient.id,
              facility_id=dept.facility_id, department_id=dept.id, visit_type="opd",
              visit_date=datetime.now(timezone.utc), created_by=doctor.id)
    db.add(v)
    await db.flush()
    return v, doctor


async def test_create_and_get_encounter(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, created_by=doctor.id, chief_complaint="fever"))

    assert encounter.chief_complaint == "fever"
    assert encounter.note_status == "pending"
    assert encounter.row_version == 1
    assert encounter.facility_id == v.facility_id

    fetched = await service.get_encounter(db, encounter.id)
    assert fetched is not None and fetched.id == encounter.id

    assert await service.get_encounter(db, uuid.uuid4()) is None


async def test_update_encounter_soap_fields(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, created_by=doctor.id, chief_complaint="cough"))

    updated = await service.update_encounter(
        db, encounter, EncounterUpdate(updated_by=doctor.id, subjective="dry cough for 3 days",
                                        assessment="viral", plan="rest", note_status="stored"))

    assert updated.subjective == "dry cough for 3 days"
    assert updated.assessment == "viral"
    assert updated.plan == "rest"
    assert updated.note_status == "stored"
    assert updated.row_version == 2
    assert updated.chief_complaint == "cough"  # untouched field stays as-is
    assert updated.objective is None


async def test_diagnosis_create_and_list(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, created_by=doctor.id))

    d1 = await service.create_diagnosis(db, DiagnosisCreate(
        encounter_id=encounter.id, created_by=doctor.id, icd_code="J11", icd_version="ICD-10",
        diagnosis_text="Influenza", diagnosis_type="provisional", is_primary=True))
    assert d1.facility_id == encounter.facility_id
    assert d1.is_primary is True

    await service.create_diagnosis(db, DiagnosisCreate(
        encounter_id=encounter.id, created_by=doctor.id, icd_code="R50.9", icd_version="ICD-10",
        diagnosis_text="Fever, unspecified", diagnosis_type="differential", is_primary=False))

    diagnoses = await service.list_diagnoses(db, encounter.id)
    assert len(diagnoses) == 2
    assert {d.icd_code for d in diagnoses} == {"J11", "R50.9"}
