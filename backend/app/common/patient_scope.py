"""Resource ownership checks shared by clinical APIs (roles alone are not scope)."""
from uuid import UUID
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import DbUser
from app.opd.models import Visit
from app.patients.models import Patient, PatientPortalBinding
from app.users.models import User, Facility


async def facility_timezone(db: AsyncSession, facility_id: UUID) -> ZoneInfo:
    name = (await db.execute(select(Facility.timezone).where(Facility.id == facility_id))).scalar_one_or_none()
    if not name:
        raise HTTPException(404, "Facility not found")
    return ZoneInfo(name)


async def facility_today(db: AsyncSession, facility_id: UUID) -> date:
    return datetime.now(await facility_timezone(db, facility_id)).date()


async def actor_facility(db: AsyncSession, user_id: UUID) -> UUID:
    facility = (await db.execute(select(User.facility_id).where(
        User.id == user_id, User.is_active.is_(True),
    ))).scalar_one_or_none()
    if facility is None:
        raise HTTPException(403, "Active facility user required")
    return facility


async def require_patient_scope(db: AsyncSession, patient_id: UUID, facility_id: UUID) -> Patient:
    patient = (await db.execute(select(Patient).where(
        Patient.id == patient_id, Patient.facility_id == facility_id,
        Patient.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient


async def require_patient_access(db: AsyncSession, patient_id: UUID, actor: DbUser) -> Patient:
    patient = await require_patient_scope(db, patient_id, actor.facility_id)
    # A patient-role credential never obtains staff access by guessing a UUID,
    # including when an account accidentally carries both role families.
    if "patient" in actor.roles:
        binding = (await db.execute(select(PatientPortalBinding.id).where(
            PatientPortalBinding.user_id == actor.id,
            PatientPortalBinding.patient_id == patient_id,
            PatientPortalBinding.facility_id == actor.facility_id,
            PatientPortalBinding.revoked_at.is_(None),
        ))).scalar_one_or_none()
        if binding is None or patient.status != "active":
            raise HTTPException(404, "Patient not found")
    return patient


async def require_visit_scope(db: AsyncSession, visit_id: UUID | None,
                              patient_id: UUID, facility_id: UUID) -> None:
    if visit_id is None:
        return
    found = (await db.execute(select(Visit.id).where(
        Visit.id == visit_id, Visit.patient_id == patient_id,
        Visit.facility_id == facility_id,
    ))).scalar_one_or_none()
    if found is None:
        raise HTTPException(404, "Visit not found for this patient")
