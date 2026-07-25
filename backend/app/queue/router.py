"""queue module router — B3-W3-01 doctor queue."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import Column, String, Text, DateTime, Table, MetaData, select, and_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Visit, Encounter
from app.queue.schemas import QueueEntry

router = APIRouter(prefix="/queue", tags=["queue"])

# Minimal read-only reference to `patients` — no ORM model exists for it elsewhere.
_metadata = MetaData()
patients_table = Table(
    "patients",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("full_name", Text),
    Column("uhid", String(30)),
)


@router.get("/ping")
async def ping() -> dict:
    return {"module": "queue", "status": "stub"}


@router.get("", response_model=list[QueueEntry])
async def get_queue(
    department_id: Optional[uuid.UUID] = None,
    provider_user_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    conditions = [Visit.status.in_(["registered", "in_consultation"])]
    if department_id is not None:
        conditions.append(Visit.department_id == department_id)

    stmt = (
        select(
            Visit.id.label("visit_id"),
            Visit.visit_number,
            Visit.patient_id,
            patients_table.c.full_name.label("patient_name"),
            patients_table.c.uhid,
            Visit.status.label("visit_status"),
            Visit.visit_date,
            Encounter.id.label("encounter_id"),
            Encounter.provider_user_id,
            Encounter.chief_complaint,
            Encounter.started_at,
        )
        .join(patients_table, patients_table.c.id == Visit.patient_id)
        .outerjoin(
            Encounter,
            and_(Encounter.visit_id == Visit.id, Encounter.ended_at.is_(None)),
        )
        .where(*conditions)
        .order_by(Visit.visit_date.asc())
    )

    if provider_user_id is not None:
        stmt = stmt.where(
            (Encounter.provider_user_id == provider_user_id) | (Encounter.id.is_(None))
        )

    result = await db.execute(stmt)
    return [QueueEntry(**row._mapping) for row in result.all()]
