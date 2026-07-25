import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.orders.models import Result, Order
from app.orders.results_schemas import ResultCreate, ResultOut, ResultReview

router = APIRouter(prefix="/results", tags=["results"])


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
    return result
