"""backend/tests/test_doctor_reviews.py -- #200: doctor review API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.opd.models import Visit
from app.patients.models import Patient
from app.encounters import service
from app.encounters.schemas import EncounterCreate


@pytest.fixture
async def encounter(db, seed):
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
    enc = await service.create_encounter(
        db, EncounterCreate(visit_id=v.id, provider_user_id=doctor.id, created_by=doctor.id,
                             chief_complaint="fever"))
    return enc, doctor


async def test_create_review_starts_pending(db, encounter):
    enc, doctor = encounter
    review = await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id)

    assert review.status == "pending"
    assert review.facility_id == enc.facility_id
    assert review.signed_off_at is None

    fetched = await service.get_review(db, review.id)
    assert fetched is not None and fetched.id == review.id


async def test_create_review_unknown_encounter_raises(db, seed):
    dept, room, doctor = seed
    with pytest.raises(service.EncounterNotFound):
        await service.create_review(db, encounter_id=uuid.uuid4(), reviewed_by=doctor.id, created_by=doctor.id)


async def test_list_reviews_for_encounter(db, encounter):
    enc, doctor = encounter
    await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id, notes="first")
    await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id, notes="second")

    reviews = await service.list_reviews(db, enc.id)
    assert len(reviews) == 2


async def test_review_transition_pending_to_reviewed_to_signed_off(db, encounter):
    enc, doctor = encounter
    review = await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id)

    review = await service.update_review_status(db, review, new_status="reviewed", updated_by=doctor.id)
    assert review.status == "reviewed"
    assert review.signed_off_at is None

    review = await service.update_review_status(
        db, review, new_status="signed_off", updated_by=doctor.id, notes="Reviewed, normal findings.")
    assert review.status == "signed_off"
    assert review.signed_off_at is not None
    assert review.notes == "Reviewed, normal findings."


async def test_review_transition_cannot_skip_reviewed(db, encounter):
    enc, doctor = encounter
    review = await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id)

    with pytest.raises(service.InvalidReviewTransition):
        await service.update_review_status(db, review, new_status="signed_off", updated_by=doctor.id)


async def test_review_transition_terminal_after_signed_off(db, encounter):
    enc, doctor = encounter
    review = await service.create_review(db, encounter_id=enc.id, reviewed_by=doctor.id, created_by=doctor.id)
    review = await service.update_review_status(db, review, new_status="reviewed", updated_by=doctor.id)
    review = await service.update_review_status(db, review, new_status="signed_off", updated_by=doctor.id)

    with pytest.raises(service.InvalidReviewTransition):
        await service.update_review_status(db, review, new_status="reviewed", updated_by=doctor.id)
