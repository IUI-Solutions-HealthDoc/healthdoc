import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.db import get_db
from app.orders.models import Prescription, PrescriptionItem
from app.orders.prescription_schemas import PrescriptionCreate, PrescriptionOut
from app.audit import service as audit_service

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.get("", response_model=list[PrescriptionOut])
async def list_prescriptions(
    patient_id: uuid.UUID | None = None,
    encounter_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Prescription).options(selectinload(Prescription.items))
    if patient_id:
        stmt = stmt.where(Prescription.patient_id == patient_id)
    if encounter_id:
        stmt = stmt.where(Prescription.encounter_id == encounter_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=PrescriptionOut, status_code=201)
async def create_prescription(payload: PrescriptionCreate, db: AsyncSession = Depends(get_db)):
    prescription = Prescription(
        encounter_id=payload.encounter_id,
        patient_id=payload.patient_id,
        created_by=payload.created_by,
        notes=payload.notes,
    )
    db.add(prescription)
    await db.flush()
    for item in payload.items:
        db.add(PrescriptionItem(
            prescription_id=prescription.id,
            medicine_name=item.medicine_name,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            route=item.route,
            instructions=item.instructions,
            status="prescribed",
        ))
    await db.flush()
    result = await db.execute(
        select(Prescription)
        .where(Prescription.id == prescription.id)
        .options(selectinload(Prescription.items))
    )
    created = result.scalar_one()

    facility_id = await audit_service.facility_id_for_encounter(db, created.encounter_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=created.created_by,
            role=None,
            action="prescription.create",
            resource_type="prescription",
            resource_id=created.id,
            patient_id=created.patient_id,
            new_value={"item_count": len(created.items)},
        )

    return created


@router.get("/{prescription_id}", response_model=PrescriptionOut)
async def get_prescription(prescription_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Prescription)
        .where(Prescription.id == prescription_id)
        .options(selectinload(Prescription.items))
    )
    prescription = result.scalar_one_or_none()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return prescription
