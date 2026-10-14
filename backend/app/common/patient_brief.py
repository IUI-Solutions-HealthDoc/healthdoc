"""Who a worklist row is for, in one batched read.

Worklists keyed on orders (lab, radiology, nursing, pharmacy) showed no
patient or only an internal id, so the person at the bench could not confirm
whom a sample, scan or medicine belonged to before acting (QA 10-12 Oct 2026).
Name, UHID, age and sex are what a wristband check uses; nothing more is
returned. Scoped to the caller's facility: a row whose patient belongs
elsewhere gets no brief rather than another hospital's name.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.patients.models import Patient


class PatientBrief(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    patient_uhid: str | None
    patient_age_years: int | None
    patient_sex: str | None


async def patient_briefs(
    db: AsyncSession, patient_ids: Iterable[uuid.UUID], facility_id: uuid.UUID,
) -> dict[uuid.UUID, PatientBrief]:
    ids = {pid for pid in patient_ids if pid is not None}
    if not ids:
        return {}
    rows = (await db.execute(
        select(Patient).where(Patient.id.in_(ids), Patient.facility_id == facility_id)
    )).scalars().all()
    return {
        p.id: PatientBrief(
            patient_id=p.id, patient_name=p.full_name, patient_uhid=p.uhid or p.thid,
            patient_age_years=p.age_years, patient_sex=p.sex,
        )
        for p in rows
    }
