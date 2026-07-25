import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Encounter
from app.encounters.schemas import EncounterCreate, EncounterUpdate, EncounterOut

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

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(encounter, field, value)

    await db.flush()
    await db.refresh(encounter)
    return encounter


@router.get("", response_model=list[EncounterOut])
async def list_encounters(visit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Encounter).where(Encounter.visit_id == visit_id))
    return result.scalars().all()
