"""
pathology module router - issue #166 (order receive + sample collection),
#184 (result entry + dual-verify), #185 (critical value SSE alert),
#186 (TAT calculation on release), #231 (lab MIS summary).

Prefix is /pathology (module-scoped). Response wrapping (envelope) and
pagination follow Master Schema Section 4 - this router returns plain
Pydantic models; the envelope middleware wraps them.

NOTE: project uses async SQLAlchemy (AsyncSession) - every DB call is awaited.

STILL OPEN (flagged, not silently fixed - see TODOs inline):
- _write_audit_log is a stub (pass). Audit logging is owned by a teammate's
  module (app/audit/models.py + migration 0003). Swap the stub once that
  lands - do not implement it here.
- CRITICAL_THRESHOLDS only has a placeholder hemoglobin range. Needs real
  values from the pathologist/lab director before this ships.
- orders/departments/users FKs on LabOrderItem/LabResult are intentionally
  omitted at the DB level too (see migration for #166) for the same reason -
  those tables don't exist yet either.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from statistics import mean, median
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.common.db import get_db
from app.auth.deps import get_current_user, require_roles, get_current_db_user, CurrentDbUser
from app.pathology.models import LabOrderItem, LabResult
from app.pathology.schemas import (
    LabOrderItemCreate, LabOrderItemOut, SampleCollectionRequest, LabOrderItemListOut,
    LabResultCreate, LabResultVerify, LabResultOut,
    LabResultAmend, LabResultHistoryOut,
    LabMISSummaryOut, TATByTestOut, StatusCountOut, PanicFrequencyOut,
)
router = APIRouter(prefix="/pathology", tags=["pathology"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "pathology", "status": "stub"}


# --- #166: order receive + sample collection ---

@router.post(
    "/order-items",
    response_model=LabOrderItemOut,
    status_code=201,
)
async def create_lab_order_item(
    payload: LabOrderItemCreate,
    order_id: uuid.UUID = Query(..., description="Existing order id (order_type=lab)"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "lab_tech")),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    try:
        from app.orders.models import Order
    except ImportError:
        Order = None

    if Order is not None:
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
        created_by=current_db_user.id,
    )
    db.add(item)
    await db.flush()

    await _write_audit_log(db, table_name="lab_order_items", row_id=item.id,
                            action="create", actor_id=current_db_user.id)
    await db.refresh(item)
    return item


@router.put(
    "/order-items/{item_id}/sample-collection",
    response_model=LabOrderItemOut,
)
async def collect_sample(
    item_id: uuid.UUID,
    payload: SampleCollectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    item = await db.get(LabOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Lab order item not found")

    if item.status != "placed":
        raise HTTPException(status_code=409, detail="Sample already collected for this item")

    duplicate = (await db.execute(
        select(func.count()).select_from(LabOrderItem)
        .where(LabOrderItem.barcode == payload.barcode)
    )).scalar()
    if duplicate:
        raise HTTPException(status_code=409, detail="Duplicate barcode")

    item.status = "in_progress"
    item.barcode = payload.barcode
    item.collected_at = payload.collected_at or datetime.now(timezone.utc)

    await _write_audit_log(db, table_name="lab_order_items", row_id=item.id,
                            action="update", actor_id=current_db_user.id)
    await db.refresh(item)
    return item


@router.get(
    "/order-items",
    response_model=LabOrderItemListOut,
)
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
        .offset((page - 1) * page_size)
        .limit(page_size)
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


# --- #184: result entry (technician) + dual-verify pathologist approval ---

CRITICAL_THRESHOLDS = {
    "hemoglobin_g_dl": {"low": 7.0, "high": 20.0},
}


def _check_critical(result_data: dict) -> list[str]:
    flagged = []
    for field, limits in CRITICAL_THRESHOLDS.items():
        value = result_data.get(field)
        if value is None:
            continue
        if value < limits["low"] or value > limits["high"]:
            flagged.append(field)
    return flagged


@router.post(
    "/order-items/{item_id}/results",
    response_model=LabResultOut,
    status_code=201,
)
async def enter_result(
    item_id: uuid.UUID,
    payload: LabResultCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    item = await db.get(LabOrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Lab order item not found")

    result = LabResult(
        lab_order_item_id=item_id,
        version=1,
        is_current=True,
        result_data=payload.result_data,
        remarks=payload.remarks,
        status="preliminary",
        created_by=current_db_user.id,
    )
    db.add(result)
    item.status = "completed"

    # #185: wire the critical-value check + doctor notification back in -
    # this call was missing entirely in this version, so alerts never fired.
    flagged = _check_critical(payload.result_data)
    if flagged:
        await _publish_critical_alert(db, item, flagged)

    await _write_audit_log(db, table_name="lab_results", row_id=result.id,
                            action="create", actor_id=current_db_user.id)
    await db.flush()
    await db.refresh(result)
    return result


@router.put(
    "/order-items/{item_id}/results/verify",
    response_model=LabResultOut,
)
async def verify_result(
    item_id: uuid.UUID,
    payload: LabResultVerify,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("pathologist")),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    current = (await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id, LabResult.is_current.is_(True))
    )).scalar_one_or_none()

    if current is None:
        raise HTTPException(status_code=404, detail="No result found for this item")

    if str(current.created_by) == str(current_db_user.id):
        raise HTTPException(
            status_code=403,
            detail="Verifying pathologist must be different from the person who entered the result",
        )

    current.is_current = False
    await db.flush()

    new_result = LabResult(
        lab_order_item_id=item_id,
        version=current.version + 1,
        is_current=True,
        result_data=payload.result_data if payload.result_data is not None else current.result_data,
        remarks=payload.remarks if payload.remarks is not None else current.remarks,
        status="final",
        created_by=current_db_user.id,
    )
    db.add(new_result)

    item = await db.get(LabOrderItem, item_id)
    item.status = "released"

    await _write_audit_log(db, table_name="lab_results", row_id=new_result.id,
                            action="create", actor_id=current_db_user.id)
    await db.flush()
    await db.refresh(new_result)

    tat_delta = new_result.created_at - (item.collected_at or item.created_at)
    result_out = LabResultOut.model_validate(new_result)
    result_out.tat_minutes = int(tat_delta.total_seconds() // 60)
    return result_out


# --- #218: report amendment (version rows, locked originals, history API) ---

@router.put(
    "/order-items/{item_id}/results/amend",
    response_model=LabResultOut,
)
async def amend_result(
    item_id: uuid.UUID,
    payload: LabResultAmend,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("pathologist")),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    current = (await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id, LabResult.is_current.is_(True))
    )).scalar_one_or_none()

    if current is None:
        raise HTTPException(status_code=404, detail="No result found for this item")
    if current.status != "final":
        raise HTTPException(status_code=409, detail="Only a finalized result can be amended")

    current.is_current = False
    await db.flush()

    amended = LabResult(
        lab_order_item_id=item_id,
        version=current.version + 1,
        is_current=True,
        result_data=payload.result_data if payload.result_data is not None else current.result_data,
        remarks=payload.remarks if payload.remarks is not None else current.remarks,
        status="corrected",
        amendment_reason=payload.amendment_reason,
        created_by=current_db_user.id,
    )
    db.add(amended)

    await _write_audit_log(db, table_name="lab_results", row_id=amended.id,
                            action="create", actor_id=current_db_user.id)
    await db.flush()
    await db.refresh(amended)
    return amended


@router.get(
    "/order-items/{item_id}/results/history",
    response_model=LabResultHistoryOut,
)
async def get_result_history(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id)
        .order_by(LabResult.version.asc())
    )
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No results found for this item")
    return LabResultHistoryOut(items=rows)


# --- #231: Lab MIS summary - TAT by test, status counts, panic frequency ---

@router.get(
    "/mis/summary",
    response_model=LabMISSummaryOut,
)
async def lab_mis_summary(
    date_from: datetime = Query(..., description="Range start, inclusive"),
    date_to: datetime = Query(..., description="Range end, inclusive"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("pathologist", "lab_tech", "doctor")),
):
    """
    Aggregates lab order items and results created within [date_from, date_to].
    Computed on the fly (not stored) - fine at current data volumes, per the
    same pattern as the single-item TAT calc in verify_result.
    """
    items_result = await db.execute(
        select(LabOrderItem).where(
            LabOrderItem.created_at >= date_from,
            LabOrderItem.created_at <= date_to,
        )
    )
    items = items_result.scalars().all()
    total_orders = len(items)

    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    order_counts_by_status = [
        StatusCountOut(status=status_name, count=count)
        for status_name, count in status_counts.items()
    ]

    results_result = await db.execute(
        select(LabResult).where(
            LabResult.created_at >= date_from,
            LabResult.created_at <= date_to,
            LabResult.status.in_(["final", "corrected"]),
        )
    )
    results = results_result.scalars().all()
    total_results = len(results)

    tat_map: dict[str, list[float]] = {}
    panic_map: dict[str, dict[str, int]] = {}

    for result in results:
        item = await db.get(LabOrderItem, result.lab_order_item_id)
        if item is None:
            continue

        baseline = item.collected_at or item.created_at
        tat_minutes = (result.created_at - baseline).total_seconds() / 60
        tat_map.setdefault(item.test_name, []).append(tat_minutes)

        panic_map.setdefault(item.test_name, {"critical": 0, "total": 0})
        panic_map[item.test_name]["total"] += 1
        if _check_critical(result.result_data):
            panic_map[item.test_name]["critical"] += 1

    tat_by_test = [
        TATByTestOut(
            test_name=name,
            sample_count=len(values),
            avg_tat_minutes=round(mean(values), 1) if values else None,
            median_tat_minutes=round(median(values), 1) if values else None,
        )
        for name, values in tat_map.items()
    ]

    panic_frequency = [
        PanicFrequencyOut(
            test_name=name,
            critical_count=stats["critical"],
            total_count=stats["total"],
            panic_rate_pct=round((stats["critical"] / stats["total"]) * 100, 1) if stats["total"] else 0.0,
        )
        for name, stats in panic_map.items()
    ]

    return LabMISSummaryOut(
        date_from=date_from,
        date_to=date_to,
        tat_by_test=tat_by_test,
        order_counts_by_status=order_counts_by_status,
        total_orders=total_orders,
        total_results=total_results,
        panic_frequency=panic_frequency,
    )


# --- #185: critical value flag -> notify ordering doctor via SSE ---

_critical_alert_subscribers: dict[str, list[asyncio.Queue]] = {}


async def _resolve_ordering_doctor_id(db: AsyncSession, item: LabOrderItem) -> uuid.UUID | None:
    try:
        from app.orders.models import Order
        from app.encounters.models import Encounter
    except ImportError:
        return None

    order = await db.get(Order, item.order_id)
    if order is None:
        return None
    encounter = await db.get(Encounter, order.encounter_id)
    if encounter is None:
        return None
    return encounter.provider_user_id


async def _publish_critical_alert(db: AsyncSession, item: LabOrderItem,
                                   flagged_fields: list[str]) -> None:
    doctor_id = await _resolve_ordering_doctor_id(db, item)
    if doctor_id is None:
        return

    try:
        from app.notifications.models import NotificationHistory
    except ImportError:
        return

    notification = NotificationHistory(
        event_type="lab_critical_result",
        payload={
            "lab_order_item_id": str(item.id),
            "accession_number": item.accession_number,
            "flagged_field_count": len(flagged_fields),
        },
        department_id=item.department_id,
    )
    db.add(notification)
    await db.flush()

    live_message = json.dumps({
        "lab_order_item_id": str(item.id),
        "accession_number": item.accession_number,
    })
    for queue in _critical_alert_subscribers.get(str(doctor_id), []):
        await queue.put(live_message)


@router.get("/critical-alerts/stream")
async def critical_alerts_stream(
    current_user=Depends(get_current_user),
    current_db_user: CurrentDbUser = Depends(get_current_db_user),
):
    # NOTE: key must be str(users.id) to match _publish_critical_alert's
    # str(doctor_id) lookup - doctor_id there comes from
    # encounter.provider_user_id, which is a users.id, not a Keycloak sub.
    subscriber_key = str(current_db_user.id)
    queue: asyncio.Queue = asyncio.Queue()
    _critical_alert_subscribers.setdefault(subscriber_key, []).append(queue)

    async def event_generator():
        try:
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
        finally:
            _critical_alert_subscribers[subscriber_key].remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")