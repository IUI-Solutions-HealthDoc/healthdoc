"""backend/app/encounters/service.py -- encounter CRUD + diagnosis create/list.

Encounter/Diagnosis are owned by app.opd.models (this module doesn't
redefine the ORM classes). facility_id on both is denormalized from
the parent row rather than caller-supplied -- required for audit
auto-logging (__audit_facility_id_field__) and safer than trusting
client input. IDs/server-default columns are set explicitly in Python
(no db.refresh() -- pre-existing SQLite test-session issue elsewhere
in this codebase, confirmed unrelated to business logic)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Diagnosis, DoctorReview, Encounter, Visit
from app.users.models import User
from app.encounters.schemas import DiagnosisCreate, EncounterCreate, EncounterUpdate
from app.queue import service as queue_service


class VisitNotFound(Exception):
    def __init__(self, visit_id: UUID):
        self.visit_id = visit_id


class ProviderNotInFacility(Exception):
    """The attending clinician named on the encounter is not a user here.

    provider_user_id is NOT forced to the caller: a nurse or receptionist
    legitimately opens an encounter for the doctor who will see the patient, so
    the attending and the author are different people and both are recorded.

    But it was previously written through from the request body with no check
    at all, which meant an encounter — and every diagnosis hanging off it —
    could be attributed to an arbitrary UUID, including a real doctor at another
    hospital. That is a medico-legal record saying a clinician saw a patient
    they never saw.
    """

    def __init__(self, provider_user_id: UUID):
        self.provider_user_id = provider_user_id


class EncounterNotFound(Exception):
    def __init__(self, encounter_id: UUID):
        self.encounter_id = encounter_id


class StaleEncounterWrite(Exception):
    def __init__(self, encounter: Encounter):
        self.encounter = encounter


class DoctorReviewNotFound(Exception):
    def __init__(self, review_id: UUID):
        self.review_id = review_id


class InvalidReviewTransition(Exception):
    """#200 -- doctor_reviews.status only ever moves forward one step:
    pending -> reviewed -> signed_off. signed_off is terminal. Skipping a
    step (pending -> signed_off) or moving backward is rejected -- a
    reviewer who wants to redo a review creates a new row, the same
    append-preferred spirit as lab_results/radiology_reports even though
    this table itself is mutable (see DoctorReview's docstring)."""

    def __init__(self, current_status: str, requested_status: str):
        self.current_status = current_status
        self.requested_status = requested_status


_ALLOWED_REVIEW_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"reviewed"},
    "reviewed": {"signed_off"},
    "signed_off": set(),
}


async def _assert_provider_in_facility(
    db: AsyncSession, provider_user_id: UUID, facility_id: UUID
) -> None:
    """The named attending must be an active user of this facility.

    `is_active` is checked too: attributing a new clinical note to a
    deactivated account is how a departed clinician keeps appearing on records.
    """
    result = await db.execute(
        select(User.id).where(
            User.id == provider_user_id,
            User.facility_id == facility_id,
            User.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise ProviderNotInFacility(provider_user_id)


async def create_encounter(
    db: AsyncSession, payload: EncounterCreate, *, actor_id: UUID, facility_id: UUID
) -> Encounter:
    """Open an encounter against a visit in the CALLER's facility.

    `actor_id` and `facility_id` are required keyword arguments with no
    defaults, so no call site can omit them and silently fall back to the
    request body — which is what this function used to do for both.

    The visit lookup is scoped. It used to be `where(Visit.id == ...)` with no
    facility predicate, and `facility_id` is then copied from whatever visit
    came back: a caller could open an encounter on another hospital's visit and
    the encounter would be stamped into that hospital. Every read in this module
    goes through `_get_scoped_encounter`, but a create has no encounter yet to
    scope — it scopes through the visit, and that path was missed. Same
    join-scoping shape as the P0.4 findings, on the write side.

    VisitNotFound rather than a distinct "wrong facility" error, for the same
    reason reads 404: a different answer would confirm the visit id exists.
    """
    result = await db.execute(
        select(Visit).where(Visit.id == payload.visit_id, Visit.facility_id == facility_id)
    )
    visit = result.scalar_one_or_none()
    if visit is None:
        raise VisitNotFound(payload.visit_id)

    await _assert_provider_in_facility(db, payload.provider_user_id, facility_id)

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=payload.visit_id,
        facility_id=visit.facility_id,
        provider_user_id=payload.provider_user_id,
        encounter_type=payload.encounter_type,
        chief_complaint=payload.chief_complaint,
        started_at=payload.started_at,
        created_by=actor_id,
        note_status="pending",
        row_version=1,
    )
    db.add(encounter)
    await db.flush()
    return encounter


async def get_encounter(db: AsyncSession, encounter_id: UUID) -> Encounter | None:
    result = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    return result.scalar_one_or_none()


async def get_latest_encounter_for_visit(
    db: AsyncSession, visit_id: UUID, facility_id: UUID
) -> Encounter | None:
    """Return the most recently opened encounter for one scoped visit.

    Standalone clinical screens use this instead of inventing an encounter id
    in the browser.  The facility predicate is deliberately on the encounter
    as well as the visit-derived identifier: a UUID from another hospital must
    remain indistinguishable from a missing visit.
    """
    result = await db.execute(
        select(Encounter)
        .where(Encounter.visit_id == visit_id, Encounter.facility_id == facility_id)
        .order_by(Encounter.started_at.desc().nullslast(), Encounter.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_encounter(
    db: AsyncSession,
    encounter: Encounter,
    payload: EncounterUpdate,
    *,
    actor_id: UUID,
    expected_row_version: int | None = None,
) -> Encounter:
    """Only overwrites fields the caller provided; row_version increments on every mutation."""
    if expected_row_version is not None and encounter.row_version != expected_row_version:
        raise StaleEncounterWrite(encounter)
    if payload.encounter_type is not None:
        encounter.encounter_type = payload.encounter_type
    if payload.chief_complaint is not None:
        encounter.chief_complaint = payload.chief_complaint
    closing_now = payload.ended_at is not None and encounter.ended_at is None
    if payload.ended_at is not None:
        encounter.ended_at = payload.ended_at
    if payload.subjective is not None:
        encounter.subjective = payload.subjective
    if payload.objective is not None:
        encounter.objective = payload.objective
    if payload.assessment is not None:
        encounter.assessment = payload.assessment
    if payload.plan is not None:
        encounter.plan = payload.plan
    if payload.note_status is not None:
        encounter.note_status = payload.note_status
    # From the token, never the body. Besides the forgery, the old line
    # assigned payload.updated_by unconditionally — and it is optional, so a
    # PATCH that omitted it NULLed out the last-editor of a clinical note.
    # Closing the note is the "consultation over" signal, so the patient's
    # queue token closes with it. Without this the encounter showed
    # "Completed" while the same patient sat in the doctor's queue as
    # "Waiting" — two screens disagreeing about the same event.
    #
    # Guarded on the TRANSITION, not on ended_at being set: a later PATCH that
    # re-sends the same ended_at must not try to complete an already-completed
    # token, and editing a closed note must not re-advance the queue.
    #
    # Same transaction as the note, deliberately. If the token cannot be
    # closed the note write goes back with it, because a consultation recorded
    # as finished while the queue still holds the patient is the exact
    # inconsistency being fixed.
    if closing_now and encounter.visit_id is not None:
        await queue_service.complete_for_visit_if_active(db, encounter.visit_id)

    encounter.updated_by = actor_id
    # Timestamps.updated_at uses SQL ``onupdate=now()``. PostgreSQL expires the
    # attribute after flush, and response serialization would then attempt an
    # implicit async SELECT outside greenlet_spawn. Set it explicitly so the
    # returned clinical row is complete without hidden I/O.
    encounter.updated_at = datetime.now(timezone.utc)
    encounter.row_version += 1
    await db.flush()
    return encounter


async def create_diagnosis(
    db: AsyncSession, payload: DiagnosisCreate, *, actor_id: UUID
) -> Diagnosis:
    result = await db.execute(select(Encounter).where(Encounter.id == payload.encounter_id))
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise EncounterNotFound(payload.encounter_id)

    diagnosis = Diagnosis(
        id=uuid.uuid4(),
        encounter_id=payload.encounter_id,
        facility_id=encounter.facility_id,
        icd_code=payload.icd_code,
        icd_version=payload.icd_version,
        icd_code_id=payload.icd_code_id,
        icd_uri=payload.icd_uri,
        post_coordinated_code=payload.post_coordinated_code,
        diagnosis_text=payload.diagnosis_text,
        diagnosis_type=payload.diagnosis_type,
        is_primary=payload.is_primary,
        # From the token. A diagnosis is the most consequential attribution in
        # the record — it drives billing, reporting and the discharge summary.
        created_by=actor_id,
    )
    db.add(diagnosis)
    await db.flush()
    return diagnosis


async def list_diagnoses(db: AsyncSession, encounter_id: UUID) -> list[Diagnosis]:
    result = await db.execute(select(Diagnosis).where(Diagnosis.encounter_id == encounter_id))
    return list(result.scalars().all())



async def create_review(
    db: AsyncSession,
    encounter_id: UUID,
    reviewed_by: UUID,
    created_by: UUID,
    lab_order_item_id: UUID | None = None,
    radiology_order_item_id: UUID | None = None,
    notes: str | None = None,
) -> DoctorReview:
    encounter = await get_encounter(db, encounter_id)
    if encounter is None:
        raise EncounterNotFound(encounter_id)

    review = DoctorReview(
        id=uuid.uuid4(),
        encounter_id=encounter_id,
        facility_id=encounter.facility_id,
        reviewed_by=reviewed_by,
        lab_order_item_id=lab_order_item_id,
        radiology_order_item_id=radiology_order_item_id,
        status="pending",
        notes=notes,
        created_by=created_by,
    )
    db.add(review)
    await db.flush()
    return review


async def get_review(db: AsyncSession, review_id: UUID) -> DoctorReview | None:
    result = await db.execute(select(DoctorReview).where(DoctorReview.id == review_id))
    return result.scalar_one_or_none()


async def list_reviews(db: AsyncSession, encounter_id: UUID) -> list[DoctorReview]:
    result = await db.execute(select(DoctorReview).where(DoctorReview.encounter_id == encounter_id))
    return list(result.scalars().all())


async def update_review_status(
    db: AsyncSession,
    review: DoctorReview,
    new_status: str,
    updated_by: UUID,
    notes: str | None = None,
) -> DoctorReview:
    allowed = _ALLOWED_REVIEW_TRANSITIONS.get(review.status, set())
    if new_status not in allowed:
        raise InvalidReviewTransition(review.status, new_status)

    review.status = new_status
    review.updated_by = updated_by
    if notes is not None:
        review.notes = notes
    if new_status == "signed_off":
        review.signed_off_at = datetime.now(timezone.utc)

    await db.flush()
    return review
