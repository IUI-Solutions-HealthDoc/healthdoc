import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Diagnosis, IcdCode
from app.encounters.diagnosis_schemas import DiagnosisCreate, DiagnosisOut, IcdSearchResult
from app.audit import service as audit_service

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])


@router.post("", response_model=DiagnosisOut, status_code=201)
async def create_diagnosis(payload: DiagnosisCreate, db: AsyncSession = Depends(get_db)):
    diagnosis = Diagnosis(**payload.model_dump())
    db.add(diagnosis)
    await db.flush()
    await db.refresh(diagnosis)

    facility_id = await audit_service.facility_id_for_encounter(db, diagnosis.encounter_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=diagnosis.created_by,
            role=None,
            action="diagnosis.create",
            resource_type="diagnosis",
            resource_id=diagnosis.id,
            new_value={
                "icd_code": diagnosis.icd_code,
                "icd_version": diagnosis.icd_version,
                "is_primary": diagnosis.is_primary,
            },
        )

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