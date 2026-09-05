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
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, chief_complaint="fever"),
        actor_id=doctor.id, facility_id=v.facility_id)

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
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, chief_complaint="cough"),
        actor_id=doctor.id, facility_id=v.facility_id)

    updated = await service.update_encounter(
        db, encounter, EncounterUpdate(
            encounter_type="follow_up", chief_complaint="persistent cough",
            subjective="dry cough for 3 days", assessment="viral", plan="rest",
            note_status="stored",
        ), actor_id=doctor.id)

    assert updated.subjective == "dry cough for 3 days"
    assert updated.assessment == "viral"
    assert updated.plan == "rest"
    assert updated.note_status == "stored"
    assert updated.row_version == 2
    assert updated.chief_complaint == "persistent cough"
    assert updated.encounter_type == "follow_up"
    assert updated.objective is None


async def test_update_encounter_rejects_a_stale_row_version(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db,
        EncounterCreate(visit_id=v.id, provider_user_id=doctor.id),
        actor_id=doctor.id,
        facility_id=v.facility_id,
    )

    with pytest.raises(service.StaleEncounterWrite):
        await service.update_encounter(
            db,
            encounter,
            EncounterUpdate(assessment="must not overwrite"),
            actor_id=doctor.id,
            expected_row_version=encounter.row_version + 1,
        )

    assert encounter.assessment is None
    assert encounter.row_version == 1


async def test_latest_encounter_for_visit_is_facility_scoped(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db,
        EncounterCreate(visit_id=v.id, provider_user_id=doctor.id),
        actor_id=doctor.id,
        facility_id=v.facility_id,
    )

    found = await service.get_latest_encounter_for_visit(db, v.id, v.facility_id)
    hidden = await service.get_latest_encounter_for_visit(db, v.id, uuid.uuid4())

    assert found is not None and found.id == encounter.id
    assert hidden is None


async def test_diagnosis_create_and_list(db, visit):
    v, doctor = visit
    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id),
        actor_id=doctor.id, facility_id=v.facility_id)

    d1 = await service.create_diagnosis(db, DiagnosisCreate(
        encounter_id=encounter.id, icd_code="J11", icd_version="ICD-10",
        diagnosis_text="Influenza", diagnosis_type="provisional", is_primary=True), actor_id=doctor.id)
    assert d1.facility_id == encounter.facility_id
    assert d1.is_primary is True

    await service.create_diagnosis(db, DiagnosisCreate(
        encounter_id=encounter.id, icd_code="R50.9", icd_version="ICD-10",
        diagnosis_text="Fever, unspecified", diagnosis_type="differential", is_primary=False), actor_id=doctor.id)

    diagnoses = await service.list_diagnoses(db, encounter.id)
    assert len(diagnoses) == 2
    assert {d.icd_code for d in diagnoses} == {"J11", "R50.9"}


# --------------------------------------------------------------------------- #
# Closing the note closes the queue token.
#
# Reported as: consultation shows "Completed" while the same patient is still
# "Waiting" in the Doctor Queue. The encounter PATCH set ended_at and nothing
# else; queue.service.complete_by_visit_id() existed but its only other mention
# in the codebase was a commented-out example.
# --------------------------------------------------------------------------- #

async def test_closing_an_encounter_completes_the_patients_queue_token(db, visit, seed):
    from datetime import date

    from app.queue import service as queue_service

    v, doctor = visit
    dept, room, _doctor = seed
    queue = await queue_service.create_queue(
        db, dept.id, doctor.id, room.id, "Q", date.today(), dept.facility_id)
    token = await queue_service.create_token(db, queue.id, v.id, "normal", queue.facility_id)
    assert token.status == "waiting"

    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, chief_complaint="fever"),
        actor_id=doctor.id, facility_id=v.facility_id)
    await service.update_encounter(
        db, encounter, EncounterUpdate(ended_at=datetime.now(timezone.utc)), actor_id=doctor.id)

    await db.refresh(token)
    assert token.status == "completed", (
        "closing the consultation must close the queue token — otherwise the "
        "encounter reads Completed while the queue still shows the patient Waiting"
    )


async def test_editing_a_closed_note_does_not_re_advance_the_queue(db, visit, seed):
    """Only the transition into ended_at triggers the queue, not every PATCH."""
    from datetime import date

    from app.queue import service as queue_service

    v, doctor = visit
    dept, room, _doctor = seed
    queue = await queue_service.create_queue(
        db, dept.id, doctor.id, room.id, "Q2", date.today(), dept.facility_id)
    first = await queue_service.create_token(db, queue.id, v.id, "normal", queue.facility_id)

    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, chief_complaint="fever"),
        actor_id=doctor.id, facility_id=v.facility_id)
    ended = datetime.now(timezone.utc)
    await service.update_encounter(db, encounter, EncounterUpdate(ended_at=ended), actor_id=doctor.id)
    await db.refresh(first)
    assert first.status == "completed"

    # A second token for the same visit stands in for "the queue moved on".
    # Re-PATCHing the closed note must not touch it.
    second = await queue_service.create_token(db, queue.id, v.id, "normal", queue.facility_id)
    await service.update_encounter(db, encounter, EncounterUpdate(ended_at=ended), actor_id=doctor.id)
    await db.refresh(second)
    assert second.status == "waiting", "re-saving a closed note must not advance the queue again"


async def test_closing_a_note_for_a_visit_with_no_token_still_works(db, visit):
    """IPD and teleconsult visits have no OPD token; the note must still close."""
    v, doctor = visit
    encounter = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, chief_complaint="admitted"),
        actor_id=doctor.id, facility_id=v.facility_id)

    updated = await service.update_encounter(
        db, encounter, EncounterUpdate(ended_at=datetime.now(timezone.utc)), actor_id=doctor.id)

    assert updated.ended_at is not None
