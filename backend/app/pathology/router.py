# """pathology module router — endpoints land here; see this module's GitHub issues."""
# from fastapi import APIRouter

# router = APIRouter(prefix="/pathology", tags=["pathology"])

# @router.get("/ping")
# async def ping() -> dict:
#     return {"module": "pathology", "status": "stub"}
"""
pathology module router — issue #166: lab order receive API + sample collection.
"""
"""
pathology module router — issue #166: lab order receive API + sample collection.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.common.db import get_db
from app.auth.deps import get_current_user, require_roles
from app.pathology.models import LabOrderItem
from app.pathology.schemas import (
    LabOrderItemCreate, LabOrderItemOut, SampleCollectionRequest, LabOrderItemListOut,
)

router = APIRouter(prefix="/pathology", tags=["pathology"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "pathology", "status": "stub"}


@router.post("/order-items", response_model=LabOrderItemOut, status_code=201)
async def create_lab_order_item(
    payload: LabOrderItemCreate,
    order_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "lab_tech")),
):
    from app.orders.models import Order

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    accession_number = await _generate_accession_number(db, prefix="LAB")

    item = LabOrderItem(
        order_id=order_id,
        accession_number=accession_number,
        test_code=payload.test_code,
        test_name=payload.test_name,
        sample_type=payload.sample_type,
        department_id=payload.department_id,
        estimated_minutes=payload.estimated_minutes,
        status="placed",
        created_by=current_user.id,
    )
    db.add(item)
    await db.flush()
    await _write_audit_log(db, table_name="lab_order_items", row_id=item.id,
                            action="create", actor_id=current_user.id)
    await db.refresh(item)
    return item


@router.put("/order-items/{item_id}/sample-collection", response_model=LabOrderItemOut)
async def collect_sample(
    item_id: uuid.UUID,
    payload: SampleCollectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),
):
    item = await db.get(LabOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Lab order item not found")
    if item.status != "placed":
        raise HTTPException(status_code=409, detail="Sample already collected for this item")

    duplicate = (await db.execute(
        select(func.count()).select_from(LabOrderItem)
        .where(LabOrderItem.accession_number == payload.barcode)
    )).scalar()
    if duplicate:
        raise HTTPException(status_code=409, detail="Duplicate barcode")

    item.status = "in_progress"
    await _write_audit_log(db, table_name="lab_order_items", row_id=item.id,
                            action="update", actor_id=current_user.id)
    await db.refresh(item)
    return item


@router.get("/order-items", response_model=LabOrderItemListOut)
async def list_lab_order_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(LabOrderItem)
    if status:
        query = query.where(LabOrderItem.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    result = await db.execute(
        query.order_by(LabOrderItem.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    rows = result.scalars().all()
    return LabOrderItemListOut(items=rows, page=page, page_size=page_size, total=total)


async def _generate_accession_number(db: AsyncSession, prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count_today = (await db.execute(
        select(func.count()).select_from(LabOrderItem)
        .where(LabOrderItem.accession_number.like(f"{prefix}-{today}-%"))
    )).scalar()
    seq = str(count_today + 1).zfill(5)
    return f"{prefix}-{today}-{seq}"


async def _write_audit_log(db: AsyncSession, *, table_name: str, row_id: uuid.UUID,
                            action: str, actor_id: uuid.UUID) -> None:
    pass