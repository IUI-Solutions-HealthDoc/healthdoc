import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.opd.models import Encounter, Visit
from app.orders.models import Result, Order
from app.orders.results_schemas import ResultCreate, ResultOut, ResultReview
from app.audit import service as audit_service

router = APIRouter(prefix="/results", tags=["results"])

async def _facility_id_for_order(db: AsyncSession, order_id: uuid.UUID) -> uuid.UUID | None:
    """Order -> Encounter -> Visit -> facility_id. Needed for audit
    logging since this router has no authenticated user to pull
    facility_id from (see module docstring note in tests/test_results.py)."""
    stmt = (
        select(Visit.facility_id)
        .join(Encounter, Encounter.visit_id == Visit.id)
        .join(Order, Order.encounter_id == Encounter.id)
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()




@router.post("", response_model=ResultOut, status_code=201)
async def create_result(payload: ResultCreate, db: AsyncSession = Depends(get_db)):
    result = Result(
        order_id=payload.order_id,
        created_by=payload.created_by,
        result_status=payload.result_status.value,
        result_text=payload.result_text,
        result_data=payload.result_data,
        performed_by=payload.performed_by,
        performed_at=payload.performed_at,
    )
    db.add(result)
    await db.flush()
    await db.refresh(result)

    facility_id = await _facility_id_for_order(db, result.order_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=result.created_by,
            role=None,
            action="result.create",
            resource_type="result",
            resource_id=result.id,
            new_value={"order_id": str(result.order_id), "result_status": result.result_status},
        )

    return result


@router.get("", response_model=list[ResultOut])
async def list_results(
    order_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Result)
    if order_id:
        stmt = stmt.where(Result.order_id == order_id)
    if patient_id:
        stmt = stmt.join(Order, Order.id == Result.order_id).where(Order.patient_id == patient_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{result_id}", response_model=ResultOut)
async def get_result(result_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Result).where(Result.id == result_id))
    result = r.scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@router.patch("/{result_id}/review", response_model=ResultOut)
async def review_result(
    result_id: uuid.UUID,
    payload: ResultReview,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Result).where(Result.id == result_id))
    result = r.scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    result.reviewed_by = payload.reviewed_by
    result.reviewed_at = datetime.now(timezone.utc)
    result.review_notes = payload.review_notes
    result.is_signed_off = payload.is_signed_off
    if payload.result_status:
        result.result_status = payload.result_status.value

    await db.flush()
    await db.refresh(result)

    facility_id = await _facility_id_for_order(db, result.order_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=result.reviewed_by,
            role=None,
            action="result.review",
            resource_type="result",
            resource_id=result.id,
            new_value={
                "result_status": result.result_status,
                "is_signed_off": result.is_signed_off,
            },
        )

    return result
