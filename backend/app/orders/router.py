"""backend/app/orders/router.py -- /orders endpoints. created_by comes
from current_db_user, never the request body."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.orders import service
from app.orders.schemas import OrderCreate, OrderOut
from app.users.models import Facility

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_order(payload: OrderCreate, current_db_user: CurrentDbUser,
                        db: AsyncSession = Depends(get_db)) -> OrderOut:
    facility = await db.get(Facility, current_db_user.facility_id)
    order = await service.create_order(db, payload, facility.timezone)
    return OrderOut.model_validate(order)


@router.get("/{order_id}", response_model=OrderOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def get_order(order_id: UUID, current_db_user: CurrentDbUser,
                     db: AsyncSession = Depends(get_db)) -> OrderOut:
    order = await service.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return OrderOut.model_validate(order)
