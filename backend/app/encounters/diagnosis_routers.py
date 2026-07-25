import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Diagnosis, IcdCode
from app.encounters.diagnosis_schemas import DiagnosisCreate, DiagnosisOut, IcdSearchResult

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])


@router.post("", response_model=DiagnosisOut, status_code=201)
async def create_diagnosis(payload: DiagnosisCreate, db: AsyncSession = Depends(get_db)):
    diagnosis = Diagnosis(**payload.model_dump())
    db.add(diagnosis)
    await db.flush()
    await db.refresh(diagnosis)
    return diagnosis


@router.get("", response_model=list[DiagnosisOut])
async def list_diagnoses(encounter_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Diagnosis).where(Diagnosis.encounter_id == encounter_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/icd-search", response_model=list[IcdSearchResult])
async def icd_search(q: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(IcdCode)
        .where(IcdCode.is_active == True)
        .where(or_(IcdCode.code.ilike(f"%{q}%"), IcdCode.title.ilike(f"%{q}%")))
        .limit(20)
    )
    result = await db.execute(stmt)
    return result.scalars().all()