"""
pathology module router - issue #166 (order receive + sample collection),
#184 (result entry + dual-verify), #185 (critical value SSE alert),
#186 (TAT calculation on release), #231 (lab MIS summary).

Prefix is /pathology (module-scoped). Response wrapping (envelope) and
pagination follow Master Schema Section 4 - this router returns plain
Pydantic models; the envelope middleware wraps them.

NOTE: project uses async SQLAlchemy (AsyncSession) - every DB call is awaited.

STILL OPEN:
- CRITICAL_THRESHOLDS only has a placeholder hemoglobin range. Needs real
  values from the pathologist/lab director before this ships. This is the
  one item here that no amount of merging fixes — it needs a clinician.

RESOLVED since this module was written (all three were "blocked on someone
else's work" and that work has landed):
- _write_audit_log was a stub waiting on app/audit; 0003 merged, so it now
  delegates to app.audit.service.write_audit_log.
- Accession numbers used COUNT(*)+1, deferred because a counters table
  needed a migration this branch couldn't chain. accession_counters (0020a)
  exists; see app/common/accession.py.
- orders/departments/users FKs are real in 0010 — those tables all exist.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from statistics import mean, median
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.deps import AuthUser, CurrentDbUser, get_current_db_user, require_roles
from app.common.accession import LAB, allocate_accession_number
from app.common.db import SessionLocal, get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.orders.models import Order
from app.pathology.models import LabOrderItem, LabResult
from app.pathology.schemas import (
    LabMISSummaryOut,
    LabOrderItemCreate,
    LabOrderItemListOut,
    LabOrderItemOut,
    LabResultAmend,
    LabResultCreate,
    LabResultHistoryOut,
    LabResultOut,
    LabResultVerify,
    PanicFrequencyOut,
    SampleCollectionRequest,
    StatusCountOut,
    TATByTestOut,
)

router = APIRouter(prefix="/pathology", tags=["pathology"])
CriticalAlertUser = Annotated[
    AuthUser, Depends(require_roles("doctor", "lab_tech"))
]


async def _get_scoped_lab_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    facility_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> LabOrderItem:
    statement = (
        select(LabOrderItem)
        .join(Order, Order.id == LabOrderItem.order_id)
        .where(LabOrderItem.id == item_id, Order.facility_id == facility_id)
    )
    if for_update:
        statement = statement.with_for_update(of=LabOrderItem)
    item = (await db.execute(statement)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Lab order item not found")
    return item

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
    current_db_user: CurrentDbUser,
    payload: LabOrderItemCreate,
    order_id: uuid.UUID = Query(..., description="Existing order id (order_type=lab)"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "lab_tech")),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,

):
    order = await db.get(Order, order_id)
    if order is None or order.facility_id != current_db_user.facility_id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.order_type != "lab":
        raise HTTPException(
            status_code=422,
            detail={"code": "order_type_mismatch", "message": "A lab item requires order_type=lab"},
        )

    endpoint = f"POST /pathology/order-items?order_id={order_id}"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return LabOrderItemOut.model_validate(cached.response_body)

    # One allocation, no retry loop. accession_counters (0020a) hands out the
    # number atomically, so there is no collision to retry against — the loop
    # that used to be here existed only because COUNT(*)+1 raced.
    #
    # The old `except IntegrityError: await db.rollback()` was worse than the
    # race it guarded: db.rollback() discards the ENTIRE session, not the
    # failed INSERT, so anything else already written in this request went
    # with it.
    accession_number = await allocate_accession_number(
        db, prefix=LAB, facility_id=current_db_user.facility_id
    )
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
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.refresh(item)
    response = LabOrderItemOut.model_validate(item)
    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            201,
            response.model_dump(mode="json"),
            current_db_user.id,
        )
    return response


@router.put(
    "/order-items/{item_id}/sample-collection",
    response_model=LabOrderItemOut,
)
async def collect_sample(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: SampleCollectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),

):
    item = await _get_scoped_lab_item(
        db, item_id, current_db_user.facility_id, for_update=True
    )

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
                            action="update", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.refresh(item)
    return item


@router.get(
    "/order-items",
    response_model=LabOrderItemListOut,
    dependencies=[Depends(require_roles("lab_tech", "doctor", "admin"))],
)
async def list_lab_order_items(
    current_db_user: CurrentDbUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(LabOrderItem)
        .join(Order, Order.id == LabOrderItem.order_id)
        .where(Order.facility_id == current_db_user.facility_id)
    )
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


async def _write_audit_log(db: AsyncSession, *, table_name: str, row_id: uuid.UUID,
                            action: str, actor_id: uuid.UUID,
                            facility_id: uuid.UUID) -> None:
    """Manual audit write, delegating to app.audit.service.

    Was a stub raising under AUDIT_LOG_ENFORCED, on the grounds that
    "app/audit is owned by a teammate's module, not yet landed". It landed
    in 0003 some time ago.

    The MANUAL path rather than listeners.py's automatic one, deliberately:
    auto-audit needs __audit_facility_id_field__ naming a column on the
    model that supplies audit_logs.facility_id, which is NOT NULL. Neither
    lab_order_items nor radiology_order_items has a facility_id column —
    they reach a facility only through orders -> encounters -> visits. So
    the caller passes it from the authenticated user instead.

    Does not commit: get_db() commits once at the end of the request, which
    is what keeps the audit row and the mutation it describes in the same
    transaction.
    """
    await write_audit_log(
        db,
        facility_id=facility_id,
        action=action,
        resource_type=table_name,
        resource_id=row_id,
        user_id=actor_id,
    )

# --- #184: result entry + dual verification by a different lab professional ---

CRITICAL_THRESHOLDS = {
    "hemoglobin_g_dl": {"low": 7.0, "high": 20.0},
}


def _check_critical(result_data: dict) -> list[str]:
    flagged = []
    for field, limits in CRITICAL_THRESHOLDS.items():
        value = result_data.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_result_value",
                    "field": field,
                    "message": "Critical-threshold fields must contain a number",
                },
            )
        if value < limits["low"] or value > limits["high"]:
            flagged.append(field)
    return flagged


@router.post(
    "/order-items/{item_id}/results",
    response_model=LabResultOut,
    status_code=201,
)
async def enter_result(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: LabResultCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),

):
    item = await _get_scoped_lab_item(
        db, item_id, current_db_user.facility_id, for_update=True
    )
    if item.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sample_not_ready_for_result",
                "current_status": item.status,
            },
        )

    existing = (
        await db.execute(
            select(LabResult).where(
                LabResult.lab_order_item_id == item_id,
                LabResult.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "result_already_exists", "result_id": str(existing.id)},
        )

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
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(result)
    return result


@router.put(
    "/order-items/{item_id}/results/verify",
    response_model=LabResultOut,
)
async def verify_result(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: LabResultVerify,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),

):
    item = await _get_scoped_lab_item(
        db, item_id, current_db_user.facility_id, for_update=True
    )
    current = (await db.execute(
        select(LabResult)
        .where(LabResult.lab_order_item_id == item_id, LabResult.is_current.is_(True))
    )).scalar_one_or_none()

    if current is None:
        raise HTTPException(status_code=404, detail="No result found for this item")

    if current.status != "preliminary":
        raise HTTPException(
            status_code=409,
            detail="Only a preliminary result can be verified; use amend for a finalized result",
        )

    if str(current.created_by) == str(current_db_user.id):
        raise HTTPException(
            status_code=403,
            detail="Verifier must be different from the person who entered the result",
        )

    # Verification is a status transition on the SAME row, not a new
    # version — only amend_result (a genuine correction) mints a new
    # version. See reviewer note on PR #260.
    current.status = "final"

    item.status = "released"

    await _write_audit_log(db, table_name="lab_results", row_id=current.id,
                            action="verify", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(current)

    tat_delta = current.updated_at - (item.collected_at or item.created_at)
    result_out = LabResultOut.model_validate(current)
    result_out.tat_minutes = int(tat_delta.total_seconds() // 60)
    return result_out


# --- #218: report amendment (version rows, locked originals, history API) ---

@router.put(
    "/order-items/{item_id}/results/amend",
    response_model=LabResultOut,
)
async def amend_result(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: LabResultAmend,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech")),

):
    await _get_scoped_lab_item(
        db, item_id, current_db_user.facility_id, for_update=True
    )
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
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(amended)
    return amended


@router.get(
    "/order-items/{item_id}/results/history",
    response_model=LabResultHistoryOut,
)
async def get_result_history(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    await _get_scoped_lab_item(db, item_id, current_db_user.facility_id)
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
    current_db_user: CurrentDbUser,
    date_from: datetime = Query(..., description="Range start, inclusive"),
    date_to: datetime = Query(..., description="Range end, inclusive"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("lab_tech", "doctor")),
):
    """
    Aggregates lab order items and results created within [date_from, date_to].
    Computed on the fly (not stored) - fine at current data volumes, per the
    same pattern as the single-item TAT calc in verify_result.
    """
    items_result = await db.execute(
        select(LabOrderItem)
        .join(Order, Order.id == LabOrderItem.order_id)
        .where(
            Order.facility_id == current_db_user.facility_id,
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

    results_rows = (await db.execute(
        select(LabResult, LabOrderItem)
        .join(LabOrderItem, LabResult.lab_order_item_id == LabOrderItem.id)
        .join(Order, Order.id == LabOrderItem.order_id)
        .where(
            Order.facility_id == current_db_user.facility_id,
            LabResult.created_at >= date_from,
            LabResult.created_at <= date_to,
            LabResult.status.in_(["final", "corrected"]),
        )
    )).all()
    total_results = len(results_rows)

    tat_map: dict[str, list[float]] = {}
    panic_map: dict[str, dict[str, int]] = {}

    for result, item in results_rows:
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


def _critical_alert_subscriber_key(current_db_user) -> str:
    """Doctors receive their orders; lab professionals receive their facility.

    The original registry used only users.id, which is correct for an ordering
    doctor but makes a lab-tech subscription permanently silent: alerts are
    published to the doctor's id, never to the technician who entered them.
    """
    if "doctor" in current_db_user.roles:
        return f"doctor:{current_db_user.id}"
    return f"facility:{current_db_user.facility_id}:lab"


async def _resolve_ordering_doctor_id(db: AsyncSession, item: LabOrderItem) -> uuid.UUID | None:
    try:
        from app.opd.models import Encounter
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

    try:
        from app.notifications.models import NotificationHistory
    except ImportError:
        return

    # facility comes off the order, not the caller and not the department:
    # lab_order_items.department_id is nullable, orders.facility_id is not
    # (0022). A critical-result alert belongs to the facility that ran the
    # test, whoever happens to be entering the result.
    from app.orders.models import Order
    order = await db.get(Order, item.order_id)
    if order is None:
        return

    notification = NotificationHistory(
        event_type="lab_critical_result",
        payload={
            "lab_order_item_id": str(item.id),
            "accession_number": item.accession_number,
            "flagged_field_count": len(flagged_fields),
        },
        department_id=item.department_id,
        facility_id=order.facility_id,
    )
    db.add(notification)
    await db.flush()

    live_message = json.dumps({
        "lab_order_item_id": str(item.id),
        "accession_number": item.accession_number,
    })
    subscriber_keys = [f"facility:{order.facility_id}:lab"]
    if doctor_id is not None:
        subscriber_keys.append(f"doctor:{doctor_id}")
    # A dual-role account can be connected through only one key, but guard
    # against delivering twice if that changes later.
    delivered: set[int] = set()
    for subscriber_key in subscriber_keys:
        for queue in _critical_alert_subscribers.get(subscriber_key, []):
            if id(queue) not in delivered:
                await queue.put(live_message)
                delivered.add(id(queue))


@router.get("/critical-alerts/stream")
async def critical_alerts_stream(
    current_user: CriticalAlertUser,
):
    # Do not inject CurrentDbUser here. It depends on get_db(), and a yielded
    # FastAPI dependency stays alive for the lifetime of a StreamingResponse.
    # Every open doctor tab therefore held one SQLAlchemy connection forever;
    # after five tabs the pool was exhausted and even /health stopped
    # responding. Resolve the app user in a short, explicitly closed session
    # before returning the stream instead.
    async with SessionLocal() as db:
        current_db_user = await get_current_db_user(current_user, db)

    subscriber_key = _critical_alert_subscriber_key(current_db_user)
    queue: asyncio.Queue = asyncio.Queue()
    _critical_alert_subscribers.setdefault(subscriber_key, []).append(queue)

    async def event_generator():
        try:
            # Flush the response headers immediately. Without an initial frame,
            # browsers and reverse proxies can leave fetch() pending until the
            # first real critical result—which makes connection failures
            # indistinguishable from a healthy, quiet laboratory.
            yield ": connected\n\n"
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
        finally:
            subscribers = _critical_alert_subscribers.get(subscriber_key, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers:
                _critical_alert_subscribers.pop(subscriber_key, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
