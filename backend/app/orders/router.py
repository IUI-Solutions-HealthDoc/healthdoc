"""backend/app/orders/router.py -- /orders endpoints. created_by comes
from current_db_user, never the request body."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.allergies.service import AllergyConflict
from app.orders import service
from app.orders.schemas import (
    OrderCreate, OrderOut, PrescriptionCreate, PrescriptionItemOut, PrescriptionOut,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_order(payload: OrderCreate, current_db_user: CurrentDbUser,
                        db: AsyncSession = Depends(get_db)) -> OrderOut:
    """No facility lookup here (see #362) -- create_order() resolves
    the business-date timezone from the encounter's own facility now,
    not the caller's. current_db_user.facility_id was never the right
    facility for this: it's whoever is logged in, which can legitimately
    differ from the facility the encounter/order actually belongs to."""
    try:
        order = await service.create_order(db, payload)
    except service.EncounterNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    return OrderOut.model_validate(order)


@router.get("/{order_id}", response_model=OrderOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def get_order(order_id: UUID, current_db_user: CurrentDbUser,
                     db: AsyncSession = Depends(get_db)) -> OrderOut:
    order = await service.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return OrderOut.model_validate(order)


@router.post("/prescriptions", response_model=PrescriptionOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "admin"))])
async def create_prescription(payload: PrescriptionCreate, current_db_user: CurrentDbUser,
                               db: AsyncSession = Depends(get_db)) -> PrescriptionOut:
    """created_by is taken from current_db_user, never the request body
    (PrescriptionCreate deliberately has no created_by field, unlike
    OrderCreate). AllergyConflict -> 409: retry the same request with
    override_reason set on the conflicting item (>=20 chars) unless the
    allergy is anaphylaxis, which can never be overridden by any role.
    Interaction warnings never block -- they come back on a 201 inside
    the response body, not as an error."""
    try:
        prescription, warnings = await service.create_prescription(
            db, payload, current_db_user.id,
        )
    except service.EncounterNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    except AllergyConflict as e:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": "allergy_conflict",
                "message": str(e),
                "absolute": e.absolute,
                "allergy_id": str(e.allergy.id),
            },
        )
    items = await service.get_prescription_items(db, prescription.id)
    return PrescriptionOut(
        id=prescription.id, encounter_id=prescription.encounter_id, facility_id=prescription.facility_id,
        patient_id=prescription.patient_id, notes=prescription.notes,
        created_at=prescription.created_at, updated_at=prescription.updated_at,
        items=[PrescriptionItemOut.model_validate(i) for i in items],
        interaction_warnings=warnings,
    )


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "pharmacist", "admin"))])
async def get_prescription(prescription_id: UUID, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db)) -> PrescriptionOut:
    prescription = await service.get_prescription(db, prescription_id)
    if prescription is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="prescription_not_found")
    items = await service.get_prescription_items(db, prescription_id)
    return PrescriptionOut(
        id=prescription.id, encounter_id=prescription.encounter_id, facility_id=prescription.facility_id,
        patient_id=prescription.patient_id, notes=prescription.notes,
        created_at=prescription.created_at, updated_at=prescription.updated_at,
        items=[PrescriptionItemOut.model_validate(i) for i in items],
    )
