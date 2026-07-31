"""patients module router — endpoints land here; see this module's GitHub issues."""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.patients.models import Patient, PatientAllergy
from app.patients.allergy_schemas import AllergyCreate, AllergyOut
from app.audit import service as audit_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "patients", "status": "stub"}


@router.post("/{patient_id}/allergies", response_model=AllergyOut, status_code=201)
async def create_allergy(
    patient_id: uuid.UUID, payload: AllergyCreate, db: AsyncSession = Depends(get_db)
):
    allergy = PatientAllergy(
        patient_id=patient_id,
        allergen=payload.allergen,
        reaction=payload.reaction,
        severity=payload.severity,
        created_by=payload.created_by,
    )
    db.add(allergy)
    await db.flush()
    await db.refresh(allergy)

    patient = await db.get(Patient, patient_id)
    if patient:
        await audit_service.write_audit_log(
            db,
            facility_id=patient.facility_id,
            user_id=allergy.created_by,
            role=None,
            action="patient_allergy.create",
            resource_type="patient_allergy",
            resource_id=allergy.id,
            patient_id=patient_id,
            new_value={"allergen": allergy.allergen, "severity": allergy.severity},
        )

    return allergy


@router.get("/{patient_id}/allergies", response_model=list[AllergyOut])
async def list_allergies(patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(PatientAllergy).where(PatientAllergy.patient_id == patient_id)
    result = await db.execute(stmt)
    return result.scalars().all()
