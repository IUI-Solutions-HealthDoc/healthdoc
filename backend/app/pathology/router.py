"""
pathology module router — issue #166 (order receive + sample collection),
#184 (result entry + dual-verify), #185 (critical value SSE alert),
#186 (TAT calculation on release).

Prefix is /pathology (module-scoped). Response wrapping (envelope) and
pagination follow Master Schema §4 - this router returns plain Pydantic
models; the envelope middleware wraps them.

NOTE: project uses async SQLAlchemy (AsyncSession) - every DB call is awaited.

STILL OPEN (flagged, not silently fixed — see TODOs inline):
- _write_audit_log is a stub (pass). Audit logging is owned by a teammate's
  module (app/audit/models.py + migration 0003). Swap the stub once that
  lands — do not implement it here.
- CRITICAL_THRESHOLDS only has a placeholder hemoglobin range. Needs real
  values from the pathologist/lab director before this ships.
- _resolve_ordering_doctor_id / _publish_critical_alert import
  app.notifications.models.NotificationHistory and app.encounters.models.Encounter.
  Confirm these modules exist and match the field names used below before
  relying on #185 end-to-end.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.common.db import get_db
from app.auth.deps import get_current_user, require_roles
from app.pathology.models import LabOrderItem, LabResult
from app.pathology.schemas import (
    LabOrderItemCreate, LabOrderItemOut, SampleCollectionRequest, LabOrderItemListOut,
    LabResultCreate, LabResultVerify, LabResultOut,
    LabResultAmend, LabResultHistoryOut,
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
    order_id: uuid.UUID = Query(..., description="Existing order id (order_type='lab')"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "lab_tech")),
):
    """
    Doctor (or authorized staff) places a lab test against an existing order.
    Pydantic already enforces test_name/sample_type are not empty.
    """
    from app.orders.models import Order  # shared orders table (migration 0008)

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


@router.put(
    "/order-items/{item_id}/sample-collection",
    response_model=LabOrderItemOut,
)
async def collect_sample(
    item_id: uuid.UUID,
    payload: SampleCollectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),
):
    """
    Records barcode + collection timestamp for a placed lab item.
    Rejects duplicate barcodes (edge case flagged in the original draft).

    NOTE: requires LabOrderItem.barcode / LabOrderItem.collected_at columns
    (added in migration 00XX_lab_barcode_collected_at.py — see that file).
    """
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
                            action="update", actor_id=current_user.id)
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
    """Powers the 'Technician Dashboard - Pending Samples' screen."""
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
    """
    LAB-YYYYMMDD-SEQ5. Placeholder counter logic - confirm with the team
    whether this should use a shared counter table (like billing_counters)
    for guaranteed gapless sequencing before this ships.
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count_today = (await db.execute(
        select(func.count()).select_from(LabOrderItem)
        .where(LabOrderItem.accession_number.like(f"{prefix}-{today}-%"))
    )).scalar()
    seq = str(count_today + 1).zfill(5)
    return f"{prefix}-{today}-{seq}"


async def _write_audit_log(db: AsyncSession, *, table_name: str, row_id: uuid.UUID,
                            action: str, actor_id: uuid.UUID) -> None:
    """TODO (teammate's module): swap this stub once app/audit/models.py +
    migration 0003 land. Do not implement here — confirmed not your task."""
    pass


# --- #184: result entry (technician) + dual-verify pathologist approval ---

CRITICAL_THRESHOLDS = {
    # PLACEHOLDER - confirm real thresholds with team; keyed by result_data field name.
    "hemoglobin_g_dl": {"low": 7.0, "high": 20.0},
}


def _check_critical(result_data: dict) -> list[str]:
    """Returns list of field names that breached a critical threshold."""
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
):
    """Technician enters the first version of a result (status=preliminary)."""
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
        created_by=current_user.id,
    )
    db.add(result)
    item.status = "completed"  # awaiting verification, not "released"

    flagged = _check_critical(payload.result_data)
    if flagged:
        await _publish_critical_alert(db, item, flagged, current_user)

    await _write_audit_log(db, table_name="lab_results", row_id=result.id,
                            action="create", actor_id=current_user.id)
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
):
    """
    Pathologist approves (or corrects + approves) the current preliminary result.
    Dual-verify rule: the approving pathologist must be a DIFFERENT user than
    whoever entered the version being approved.
    """
    current = (await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id, LabResult.is_current.is_(True))
    )).scalar_one_or_none()

    if current is None:
        raise HTTPException(status_code=404, detail="No result found for this item")

    if current.created_by == current_user.id:
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
        created_by=current_user.id,
    )
    db.add(new_result)

    item = await db.get(LabOrderItem, item_id)
    item.status = "released"

    await _write_audit_log(db, table_name="lab_results", row_id=new_result.id,
                            action="create", actor_id=current_user.id)
    await db.flush()
    await db.refresh(new_result)

    # #186: TAT - calculated on the fly, not stored.
    # Baseline is collected_at when available (falls back to created_at until
    # every item has gone through the fixed sample-collection flow).
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
):
    """
    Amends an already-final result. The original version row is never
    mutated (locked) - a new version is appended with status='corrected'
    and a required amendment_reason.
    """
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
        created_by=current_user.id,
    )
    db.add(amended)

    await _write_audit_log(db, table_name="lab_results", row_id=amended.id,
                            action="create", actor_id=current_user.id)
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
    """Full version history for a lab result, oldest first. Includes locked originals."""
    result = await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id)
        .order_by(LabResult.version.asc())
    )
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No results found for this item")
    return LabResultHistoryOut(items=rows)


# --- #185: critical value flag -> notify ordering doctor via SSE ---
#
# Doctor lookup confirmed via schema §3:
#   lab_order_items.order_id -> orders.encounter_id -> encounters.provider_user_id
# Durable record goes to notification_history (0020), payload IDs-only per the
# PII rule (no patient name/UHID/clinical values in that table).
# Live delivery uses an in-process asyncio broadcaster (not Redis) since no
# pub/sub client name is confirmed yet - fine for a single-worker deployment;
# revisit if the app runs multiple uvicorn workers/processes in production.

_critical_alert_subscribers: dict[uuid.UUID, list[asyncio.Queue]] = {}


async def _resolve_ordering_doctor_id(db: AsyncSession, item: LabOrderItem) -> uuid.UUID | None:
    from app.orders.models import Order
    from app.encounters.models import Encounter  # confirm module/fields before relying on this

    order = await db.get(Order, item.order_id)
    if order is None:
        return None
    encounter = await db.get(Encounter, order.encounter_id)
    if encounter is None:
        return None
    return encounter.provider_user_id


async def _publish_critical_alert(db: AsyncSession, item: LabOrderItem,
                                   flagged_fields: list[str], actor) -> None:
    doctor_id = await _resolve_ordering_doctor_id(db, item)
    if doctor_id is None:
        return  # can't notify if the doctor can't be resolved - log/alert ops separately

    # Durable, audited record - IDs only, no clinical values or patient identity
    from app.notifications.models import NotificationHistory  # confirm module/fields before relying on this
    notification = NotificationHistory(
        event_type="lab_critical_result",
        payload={
            "lab_order_item_id": str(item.id),
            "accession_number": item.accession_number,
            "flagged_field_count": len(flagged_fields),  # count only, not field names/values
        },
        department_id=item.department_id,
    )
    db.add(notification)
    await db.flush()

    # Live push to any doctor currently connected via SSE
    live_message = json.dumps({
        "lab_order_item_id": str(item.id),
        "accession_number": item.accession_number,
    })
    for queue in _critical_alert_subscribers.get(doctor_id, []):
        await queue.put(live_message)


@router.get("/critical-alerts/stream")
async def critical_alerts_stream(
    current_user=Depends(get_current_user),
):
    """SSE stream for the logged-in doctor's critical value alerts."""
    queue: asyncio.Queue = asyncio.Queue()
    _critical_alert_subscribers.setdefault(current_user.id, []).append(queue)

    async def event_generator():
        try:
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
        finally:
            _critical_alert_subscribers[current_user.id].remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")