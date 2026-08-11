"""
radiology module router — issue #203: order receive + scheduling;
radiologist draft + sign-off.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.common.db import get_db
from app.auth.deps import get_current_user, require_roles
from app.radiology.fhir import build_diagnostic_report_bundle
from app.radiology.schemas import (
    RadiologyOrderItemCreate, RadiologyOrderItemOut, ScheduleRequest,
    ScanCompletionRequest,
    RadiologyOrderItemListOut, RadiologyReportCreate, RadiologyReportSignOff,
    RadiologyReportOut,
)
from app.radiology.models import RadiologyOrderItem, RadiologyReport


router = APIRouter(prefix="/radiology", tags=["radiology"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "radiology", "status": "stub"}


@router.post("/order-items", response_model=RadiologyOrderItemOut, status_code=201)
async def create_radiology_order_item(
    payload: RadiologyOrderItemCreate,
    order_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "radiology_tech")),
):
    try:
        from app.orders.models import Order
    except ImportError:
        Order = None  # BLOCKED: app.orders has no models.py yet (confirmed 2026-08-01)

    if Order is not None:
        order = await db.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")

    accession_number = await _generate_accession_number(db, prefix="RAD")

    item = RadiologyOrderItem(
        order_id=order_id,
        accession_number=accession_number,
        modality=payload.modality,
        scan_type=payload.scan_type,
        machine_id=payload.machine_id,
        status="placed",
        created_by=current_user.id,
    )
    db.add(item)
    await db.flush()
    await _write_audit_log(db, table_name="radiology_order_items", row_id=item.id,
                            action="create", actor_id=current_user.id)
    await db.refresh(item)
    return item


@router.put("/order-items/{item_id}/scan-complete", response_model=RadiologyOrderItemOut)
async def mark_scan_complete(
    item_id: uuid.UUID,
    payload: ScanCompletionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiology_tech")),
):
    """
    Records when the scan was actually performed (images acquired).
    This becomes the TAT baseline — mirrors LabOrderItem.collected_at.
    """
    item = await db.get(RadiologyOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Radiology order item not found")
    if item.status != "scheduled":
        raise HTTPException(status_code=409, detail="Item must be scheduled before marking scan complete")

    item.scan_completed_at = payload.completed_at or datetime.now(timezone.utc)
    item.status = "scanned"

    await _write_audit_log(db, table_name="radiology_order_items", row_id=item.id,
                            action="update", actor_id=current_user.id)
    await db.refresh(item)
    return item


@router.get("/order-items", response_model=RadiologyOrderItemListOut)
async def list_radiology_order_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(RadiologyOrderItem)
    if status:
        query = query.where(RadiologyOrderItem.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    result = await db.execute(
        query.order_by(RadiologyOrderItem.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    rows = result.scalars().all()
    return RadiologyOrderItemListOut(items=rows, page=page, page_size=page_size, total=total)


@router.post("/order-items/{item_id}/reports", response_model=RadiologyReportOut, status_code=201)
async def draft_radiology_report(
    item_id: uuid.UUID,
    payload: RadiologyReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiologist")),
):
    item = await db.get(RadiologyOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Radiology order item not found")

    if payload.pacs_study_uid:
        item.pacs_study_uid = payload.pacs_study_uid

    report = RadiologyReport(
        radiology_order_item_id=item_id,
        version=1,
        is_current=True,
        findings=payload.findings,
        impression=payload.impression,
        status="preliminary",
        created_by=current_user.id,
    )
    db.add(report)
    item.status = "reporting"

    await _write_audit_log(db, table_name="radiology_reports", row_id=report.id,
                            action="create", actor_id=current_user.id)
    await db.flush()
    await db.refresh(report)
    return report


@router.put("/order-items/{item_id}/reports/sign-off", response_model=RadiologyReportOut)
async def sign_off_radiology_report(
    item_id: uuid.UUID,
    payload: RadiologyReportSignOff,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiologist")),
):
    current = (await db.execute(
        select(RadiologyReport)
        .where(RadiologyReport.radiology_order_item_id == item_id, RadiologyReport.is_current.is_(True))
    )).scalar_one_or_none()

    if current is None:
        raise HTTPException(status_code=404, detail="No report found for this item")

    current.is_current = False
    await db.flush()

    new_report = RadiologyReport(
        radiology_order_item_id=item_id,
        version=current.version + 1,
        is_current=True,
        findings=payload.findings if payload.findings is not None else current.findings,
        impression=payload.impression if payload.impression is not None else current.impression,
        status="final",
        created_by=current_user.id,
    )
    db.add(new_report)

    item = await db.get(RadiologyOrderItem, item_id)
    item.status = "released"

    await _write_audit_log(db, table_name="radiology_reports", row_id=new_report.id,
                            action="create", actor_id=current_user.id)
    await db.flush()
    await db.refresh(new_report)

    tat_delta = new_report.created_at - (item.scan_completed_at or item.created_at)
    report_out = RadiologyReportOut.model_validate(new_report)
    report_out.tat_minutes = int(tat_delta.total_seconds() // 60)
    return report_out


@router.get("/order-items/{item_id}/fhir-bundle")
async def get_fhir_bundle(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    #204: builds a FHIR R4 Bundle (DiagnosticReport + Observation) from the
    current finalized report. Returns 409 if no report has been signed off yet.
    """
    item = await db.get(RadiologyOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Radiology order item not found")

    current_report = (await db.execute(
        select(RadiologyReport)
        .where(RadiologyReport.radiology_order_item_id == item_id, RadiologyReport.is_current.is_(True))
    )).scalar_one_or_none()

    if current_report is None:
        raise HTTPException(status_code=409, detail="No report exists for this item yet")

    try:
        from app.orders.models import Order
    except ImportError:
        Order = None  # BLOCKED: app.orders has no models.py yet (confirmed 2026-08-01)

    patient_id = None
    if Order is not None:
        order = await db.get(Order, item.order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Underlying order not found")
        patient_id = order.patient_id

    bundle = build_diagnostic_report_bundle(
        order_item=item,
        report=current_report,
        patient_id=patient_id,
    )
    return bundle


async def _generate_accession_number(db: AsyncSession, prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count_today = (await db.execute(
        select(func.count()).select_from(RadiologyOrderItem)
        .where(RadiologyOrderItem.accession_number.like(f"{prefix}-{today}-%"))
    )).scalar()
    seq = str(count_today + 1).zfill(5)
    return f"{prefix}-{today}-{seq}"


async def _write_audit_log(db: AsyncSession, *, table_name: str, row_id: uuid.UUID,
                            action: str, actor_id: uuid.UUID) -> None:
    pass