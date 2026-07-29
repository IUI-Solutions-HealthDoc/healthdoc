import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.auth.deps import require_roles
from app.nursing.models import NursingHandoverNote, IntakeOutputRecord
from app.nursing.schemas import (
    HandoverNoteCreate, HandoverNoteOut, IntakeOutputCreate, IntakeOutputOut,
)

router = APIRouter(prefix="/nursing", tags=["nursing"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "nursing", "status": "ok"}


@router.post(
    "/handover-notes",
    response_model=HandoverNoteOut,
    status_code=201,
    dependencies=[Depends(require_roles("nurse", "admin"))],
)
async def create_handover_note(payload: HandoverNoteCreate, db: AsyncSession = Depends(get_db)):
    note = NursingHandoverNote(**payload.model_dump())
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


@router.get("/admissions/{admission_id}/handover-notes", response_model=list[HandoverNoteOut])
async def list_handover_notes(admission_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(NursingHandoverNote)
        .where(NursingHandoverNote.admission_id == admission_id)
        .order_by(NursingHandoverNote.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/intake-output",
    response_model=IntakeOutputOut,
    status_code=201,
    dependencies=[Depends(require_roles("nurse", "admin"))],
)
async def create_intake_output(payload: IntakeOutputCreate, db: AsyncSession = Depends(get_db)):
    record = IntakeOutputRecord(**payload.model_dump())
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


@router.get("/admissions/{admission_id}/intake-output", response_model=list[IntakeOutputOut])
async def list_intake_output(admission_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(IntakeOutputRecord)
        .where(IntakeOutputRecord.admission_id == admission_id)
        .order_by(IntakeOutputRecord.recorded_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()
