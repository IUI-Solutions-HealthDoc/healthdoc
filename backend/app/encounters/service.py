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
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Diagnosis, Encounter, Visit
from app.encounters.schemas import DiagnosisCreate, EncounterCreate, EncounterUpdate


class VisitNotFound(Exception):
    def __init__(self, visit_id: UUID):
        self.visit_id = visit_id


class EncounterNotFound(Exception):
    def __init__(self, encounter_id: UUID):
        self.encounter_id = encounter_id


async def create_encounter(db: AsyncSession, payload: EncounterCreate) -> Encounter:
    result = await db.execute(select(Visit).where(Visit.id == payload.visit_id))
    visit = result.scalar_one_or_none()
    if visit is None:
        raise VisitNotFound(payload.visit_id)

    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=payload.visit_id,
        facility_id=visit.facility_id,
        provider_user_id=payload.provider_user_id,
        encounter_type=payload.encounter_type,
        chief_complaint=payload.chief_complaint,
        started_at=payload.started_at,
        created_by=payload.created_by,
        note_status="pending",
        row_version=1,
    )
    db.add(encounter)
    await db.flush()
    return encounter


async def get_encounter(db: AsyncSession, encounter_id: UUID) -> Encounter | None:
    result = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    return result.scalar_one_or_none()


async def update_encounter(db: AsyncSession, encounter: Encounter, payload: EncounterUpdate) -> Encounter:
    """Only overwrites fields the caller provided; row_version increments on every mutation."""
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
    encounter.updated_by = payload.updated_by
    encounter.row_version += 1
    await db.flush()
    return encounter


async def create_diagnosis(db: AsyncSession, payload: DiagnosisCreate) -> Diagnosis:
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
        created_by=payload.created_by,
    )
    db.add(diagnosis)
    await db.flush()
    return diagnosis


async def list_diagnoses(db: AsyncSession, encounter_id: UUID) -> list[Diagnosis]:
    result = await db.execute(select(Diagnosis).where(Diagnosis.encounter_id == encounter_id))
    return list(result.scalars().all())
