import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.common.enums import OrderStatus
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOut, OrderStatusUpdate
from app.orders.order_number import generate_order_number
from app.audit import service as audit_service

router = APIRouter(prefix="/orders", tags=["orders"])

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PLACED.value: {OrderStatus.ACCEPTED.value, OrderStatus.CANCELLED.value},
    OrderStatus.ACCEPTED.value: {OrderStatus.IN_PROGRESS.value, OrderStatus.CANCELLED.value},
    OrderStatus.IN_PROGRESS.value: {OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value},
    OrderStatus.COMPLETED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    order = Order(
        order_number=await generate_order_number(db),
        encounter_id=payload.encounter_id,
        patient_id=payload.patient_id,
        created_by=payload.created_by,
        order_type=payload.order_type.value,
        priority=payload.priority.value,
        status=OrderStatus.PLACED.value,
        ordered_at=datetime.now(timezone.utc),
    )
    db.add(order)
    await db.flush()
    await db.refresh(order)

    facility_id = await audit_service.facility_id_for_encounter(db, order.encounter_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=order.created_by,
            role=None,
            action="order.create",
            resource_type="order",
            resource_id=order.id,
            patient_id=order.patient_id,
            new_value={"order_type": order.order_type, "order_number": order.order_number, "status": order.status},
        )

    return order


@router.get("", response_model=list[OrderOut])
async def list_orders(
    patient_id: uuid.UUID | None = None,
    encounter_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Order)
    if patient_id:
        stmt = stmt.where(Order.patient_id == patient_id)
    if encounter_id:
        stmt = stmt.where(Order.encounter_id == encounter_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = payload.status.value
    allowed = _ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition order from '{order.status}' to '{new_status}'",
        )

    old_status = order.status
    order.status = new_status
    await db.flush()
    await db.refresh(order)

    facility_id = await audit_service.facility_id_for_encounter(db, order.encounter_id)
    if facility_id:
        await audit_service.write_audit_log(
            db,
            facility_id=facility_id,
            user_id=order.created_by,
            role=None,
            action="order.status_update",
            resource_type="order",
            resource_id=order.id,
            patient_id=order.patient_id,
            old_value={"status": old_status},
            new_value={"status": order.status},
        )

    return order
