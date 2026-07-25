import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Vitals
from app.encounters.vitals_schemas import VitalsCreate, VitalsOut

router = APIRouter(prefix="/encounters", tags=["vitals"])


@router.post("/{encounter_id}/vitals", response_model=VitalsOut, status_code=201)
async def record_vitals(
    encounter_id: uuid.UUID,
    payload: VitalsCreate,
    db: AsyncSession = Depends(get_db),
):
    vitals = Vitals(**payload.model_dump(exclude={"encounter_id"}), encounter_id=encounter_id)
    db.add(vitals)
    await db.flush()
    await db.refresh(vitals)
    return vitals


@router.get("/{encounter_id}/vitals", response_model=list[VitalsOut])
async def list_vitals(encounter_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Vitals)
        .where(Vitals.encounter_id == encounter_id)
        .order_by(Vitals.recorded_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()
