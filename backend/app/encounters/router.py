import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Encounter
from app.encounters.schemas import EncounterCreate, EncounterUpdate, EncounterOut
from app.audit import service as audit_service

router = APIRouter(prefix="/encounters", tags=["encounters"])


@router.post("", response_model=EncounterOut, status_code=201)
async def create_encounter(payload: EncounterCreate, db: AsyncSession = Depends(get_db)):
    encounter = Encounter(
        visit_id=payload.visit_id,
        provider_user_id=payload.provider_user_id,
        created_by=payload.created_by,
        encounter_type=payload.encounter_type,
        chief_complaint=payload.chief_complaint,
        started_at=datetime.now(timezone.utc),
    )
    db.add(encounter)
    await db.flush()
    await db.refresh(encounter)

    facility_id = await audit_service.facility_id_for_encounter(db, encounter.id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=encounter.created_by,
            role=None,
            action="encounter.create",
            resource_type="encounter",
            resource_id=encounter.id,
            visit_id=encounter.visit_id,
            new_value={"encounter_type": encounter.encounter_type, "chief_complaint": encounter.chief_complaint},
        )

    return encounter


@router.get("/{encounter_id}", response_model=EncounterOut)
async def get_encounter(encounter_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")
    return encounter


@router.patch("/{encounter_id}", response_model=EncounterOut)
async def update_encounter(
    encounter_id: uuid.UUID,
    payload: EncounterUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    changed_fields = payload.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(encounter, field, value)

    await db.flush()
    await db.refresh(encounter)

    facility_id = await audit_service.facility_id_for_encounter(db, encounter.id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=encounter.created_by,
            role=None,
            action="encounter.update",
            resource_type="encounter",
            resource_id=encounter.id,
            visit_id=encounter.visit_id,
            new_value=changed_fields,
        )

    return encounter


@router.get("", response_model=list[EncounterOut])
async def list_encounters(visit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Encounter).where(Encounter.visit_id == visit_id))
    return result.scalars().all()
