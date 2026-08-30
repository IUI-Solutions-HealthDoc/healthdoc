"""
radiology module router - issue #203: order receive + scheduling;
radiologist draft + sign-off.
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.accession import RADIOLOGY, allocate_accession_number
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.radiology.fhir import build_diagnostic_report_bundle
from app.radiology.models import RadiologyOrderItem, RadiologyReport
from app.radiology.schemas import (
    CancelScanRequest,
    RadiologyOrderItemCreate,
    RadiologyOrderItemListOut,
    RadiologyOrderItemOut,
    RadiologyReportCreate,
    RadiologyReportHistoryOut,
    RadiologyReportOut,
    RadiologyReportSignOff,
    RescheduleRequest,
    ScanCompletionRequest,
    ScheduleRequest,
)

router = APIRouter(prefix="/radiology", tags=["radiology"])


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "radiology", "status": "stub"}


async def _scoped_item(
    db: AsyncSession, item_id: uuid.UUID, caller_facility_id
) -> RadiologyOrderItem:
    """One radiology order item, or 404 — including when it belongs elsewhere.

    `radiology_order_items` has no `facility_id` of its own. It reaches one only
    through `order_id -> orders.facility_id`, and before this every handler in
    the module fetched by id with `db.get()` and compared nothing: scheduling,
    scan-complete, drafting a report, signing one off, and the FHIR bundle.

    The audit trail made it worse rather than better. `_write_audit_log` stamps
    `facility_id=current_db_user.facility_id`, so a cross-facility write
    recorded itself against the *caller's* facility — the row that should have
    exposed the act instead filed it under the wrong hospital.

    404 rather than 403: 403 confirms the id exists, which is enough to
    enumerate another facility's scans by accession.
    """
    from app.orders.models import Order

    item = (
        await db.execute(
            select(RadiologyOrderItem)
            .join(Order, Order.id == RadiologyOrderItem.order_id)
            .where(
                RadiologyOrderItem.id == item_id,
                Order.facility_id == caller_facility_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Radiology order item not found")
    return item


@router.post("/order-items", response_model=RadiologyOrderItemOut, status_code=201)
async def create_radiology_order_item(
    current_db_user: CurrentDbUser,
    payload: RadiologyOrderItemCreate,
    order_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "radiology_tech")),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,

):
    try:
        from app.orders.models import Order
    except ImportError:
        Order = None

    if Order is not None:
        order = await db.get(Order, order_id)
        # The facility comparison was missing: an order at another hospital
        # would accept a new scan item, and the accession number below is
        # allocated from *our* counter, so their scan would carry our sequence.
        if order is None or order.facility_id != current_db_user.facility_id:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.order_type != "radiology":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "order_type_mismatch",
                    "message": "A radiology item requires order_type=radiology",
                },
            )

    endpoint = f"POST /radiology/order-items?order_id={order_id}"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return RadiologyOrderItemOut.model_validate(cached.response_body)

    # One allocation, no retry loop — accession_counters (0020a) is atomic.
    # The old `except IntegrityError: await db.rollback()` rolled back the
    # whole session, not just the failed INSERT.
    accession_number = await allocate_accession_number(
        db, prefix=RADIOLOGY, facility_id=current_db_user.facility_id
    )
    item = RadiologyOrderItem(
        order_id=order_id,
        accession_number=accession_number,
        modality=payload.modality,
        scan_type=payload.scan_type,
        machine_id=payload.machine_id,
        status="placed",
        created_by=current_db_user.id,
    )
    db.add(item)
    await db.flush()
    await _write_audit_log(db, table_name="radiology_order_items", row_id=item.id,
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.refresh(item)
    response = RadiologyOrderItemOut.model_validate(item)
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


@router.put("/order-items/{item_id}/schedule", response_model=RadiologyOrderItemOut)
async def schedule_scan(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiology_tech", "admin")),
):
    """Book a scan onto a machine and a time — the step that was missing.

    `ScheduleRequest` existed as a schema and was imported by this module, but
    no route ever used it. Items are created `placed`; `mark_scan_complete`
    below refuses anything that is not `scheduled`; and nothing in the
    application set that status. So **no radiology scan could ever be marked
    complete**, and the workflow stopped at its first step.

    Same shape as billing's draft -> issued gap: a status transition the schema
    anticipates, with no code to perform it.

    Only from `placed`. Re-scheduling an already-scheduled scan is a legitimate
    thing to want, but it is a different operation — it has to say what happened
    to the original slot — and inventing it silently here would be guessing.
    """
    item = await _scoped_item(db, item_id, current_db_user.facility_id)

    if item.status != "placed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_schedulable",
                "message": (
                    f"Item is '{item.status}'. Only a placed scan can be scheduled."
                ),
            },
        )

    if payload.scheduled_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "scheduled_in_the_past",
                "message": "A scan cannot be booked into the past.",
            },
        )

    item.scheduled_at = payload.scheduled_at
    item.machine_id = payload.machine_id
    item.status = "scheduled"

    await _write_audit_log(db, table_name="radiology_order_items", row_id=item.id,
                            action="update", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(item)
    return item


@router.put("/order-items/{item_id}/reschedule", response_model=RadiologyOrderItemOut)
async def reschedule_scan(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: RescheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiology_tech", "admin")),
):
    item = await _scoped_item(db, item_id, current_db_user.facility_id)
    if item.status != "scheduled":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_reschedulable",
                "message": "Only a scheduled, unperformed scan can be rescheduled.",
            },
        )
    if payload.scheduled_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "scheduled_in_the_past",
                "message": "A scan cannot be booked into the past.",
            },
        )

    previous = {
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "machine_id": item.machine_id,
        "status": item.status,
    }
    item.scheduled_at = payload.scheduled_at
    item.machine_id = payload.machine_id.strip()
    await _write_audit_log(
        db,
        table_name="radiology_order_items",
        row_id=item.id,
        action="reschedule",
        actor_id=current_db_user.id,
        facility_id=current_db_user.facility_id,
        old_value=previous,
        new_value={
            "scheduled_at": item.scheduled_at.isoformat(),
            "machine_id": item.machine_id,
            "status": item.status,
        },
        reason=payload.reason.strip(),
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.put("/order-items/{item_id}/cancel", response_model=RadiologyOrderItemOut)
async def cancel_scan(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: CancelScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiology_tech", "admin")),
):
    item = await _scoped_item(db, item_id, current_db_user.facility_id)
    if item.status not in {"placed", "scheduled"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_cancellable",
                "message": "A scan cannot be cancelled after imaging has started.",
            },
        )

    previous_status = item.status
    item.status = "cancelled"
    await _write_audit_log(
        db,
        table_name="radiology_order_items",
        row_id=item.id,
        action="cancel",
        actor_id=current_db_user.id,
        facility_id=current_db_user.facility_id,
        old_value={"status": previous_status},
        new_value={"status": "cancelled"},
        reason=payload.reason.strip(),
    )
    await db.flush()
    await db.refresh(item)
    return item


@router.put("/order-items/{item_id}/scan-complete", response_model=RadiologyOrderItemOut)
async def mark_scan_complete(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: ScanCompletionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("radiology_tech")),

):
    item = await _scoped_item(db, item_id, current_db_user.facility_id)
    if item.status != "scheduled":
        raise HTTPException(status_code=409, detail="Item must be scheduled before marking scan complete")

    item.scan_completed_at = payload.completed_at or datetime.now(timezone.utc)
    item.status = "scanned"

    await _write_audit_log(db, table_name="radiology_order_items", row_id=item.id,
                            action="update", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(item)
    return item


@router.get("/order-items", response_model=RadiologyOrderItemListOut)
async def list_radiology_order_items(
    current_db_user: CurrentDbUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    # Was `get_current_user` with no role dependency, so any authenticated
    # account of any role could page the worklist.
    current_user=Depends(require_roles("doctor", "radiology_tech", "admin")),
):
    from app.orders.models import Order

    # `select(RadiologyOrderItem)` with no join returned every radiology item in
    # the deployment, paged and filterable by status — a worklist of every
    # hospital's scans, with accession numbers.
    query = (
        select(RadiologyOrderItem)
        .join(Order, Order.id == RadiologyOrderItem.order_id)
        .where(Order.facility_id == current_db_user.facility_id)
    )
    if status:
        query = query.where(RadiologyOrderItem.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    result = await db.execute(
        query.order_by(RadiologyOrderItem.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    rows = result.scalars().all()
    return RadiologyOrderItemListOut(items=rows, page=page, page_size=page_size, total=total)


@router.get("/order-items/{item_id}/reports", response_model=RadiologyReportHistoryOut)
async def list_radiology_reports(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor", "radiology_tech", "admin")),
):
    """Every version of the report for this scan, newest first.

    This did not exist. A radiologist could draft a report (POST) and sign it
    off (PUT), but nothing could read one back: the ordering doctor's only route
    to the findings was the FHIR bundle, which returns just the current version
    inside a DiagnosticReport document. Pathology has carried the equivalent
    (`/results/history`) since #218 — the asymmetry was an oversight, not a
    decision.

    Version history rather than the current row alone, for the same reason
    pathology keeps it: a preliminary read that was revised on final is what a
    treating doctor needs to see, and `is_current` cannot show that it changed.

    Empty list, not 404, when the scan exists but has no report yet — "not
    reported" is a legitimate state of a real order, distinct from "no such
    order".
    """
    await _scoped_item(db, item_id, current_db_user.facility_id)

    rows = (
        await db.execute(
            select(RadiologyReport)
            .where(RadiologyReport.radiology_order_item_id == item_id)
            .order_by(RadiologyReport.version.desc())
        )
    ).scalars().all()

    return RadiologyReportHistoryOut(
        items=[RadiologyReportOut.model_validate(r) for r in rows]
    )


@router.post("/order-items/{item_id}/reports", response_model=RadiologyReportOut, status_code=201)
async def draft_radiology_report(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: RadiologyReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor")),

):
    item = await _scoped_item(db, item_id, current_db_user.facility_id)

    if payload.pacs_study_uid:
        item.pacs_study_uid = payload.pacs_study_uid

    report = RadiologyReport(
        radiology_order_item_id=item_id,
        version=1,
        is_current=True,
        findings=payload.findings,
        impression=payload.impression,
        status="preliminary",
        created_by=current_db_user.id,
    )
    db.add(report)
    item.status = "reporting"

    await _write_audit_log(db, table_name="radiology_reports", row_id=report.id,
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(report)
    return report


@router.put("/order-items/{item_id}/reports/sign-off", response_model=RadiologyReportOut)
async def sign_off_radiology_report(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    payload: RadiologyReportSignOff,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("doctor")),

):
    # Scoped before the report is read, not after. This is the most serious of
    # the six: it writes a *final*, signed radiology report — the version a
    # clinician acts on — and the old code reached the item by bare id only to
    # set its status, several statements after the report had already been
    # superseded.
    item = await _scoped_item(db, item_id, current_db_user.facility_id)

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
        created_by=current_db_user.id,
    )
    db.add(new_report)

    item.status = "released"

    await _write_audit_log(db, table_name="radiology_reports", row_id=new_report.id,
                            action="create", actor_id=current_db_user.id,
                            facility_id=current_db_user.facility_id)
    await db.flush()
    await db.refresh(new_report)

    tat_delta = new_report.created_at - (item.scan_completed_at or item.created_at)
    report_out = RadiologyReportOut.model_validate(new_report)
    report_out.tat_minutes = int(tat_delta.total_seconds() // 60)
    return report_out


@router.get("/order-items/{item_id}/fhir-bundle")
async def get_fhir_bundle(
    current_db_user: CurrentDbUser,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # No role dependency and no facility scope, on an endpoint that returns a
    # FHIR DiagnosticReport: patient demographics, findings and impression in
    # one document. Any authenticated account of any role, by item id.
    current_user=Depends(require_roles("doctor", "radiology_tech", "admin")),
):
    item = await _scoped_item(db, item_id, current_db_user.facility_id)

    current_report = (await db.execute(
        select(RadiologyReport)
        .where(RadiologyReport.radiology_order_item_id == item_id, RadiologyReport.is_current.is_(True))
    )).scalar_one_or_none()

    if current_report is None:
        raise HTTPException(status_code=409, detail="No report exists for this item yet")

    try:
        from app.orders.models import Order
    except ImportError:
        Order = None

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


async def _write_audit_log(db: AsyncSession, *, table_name: str, row_id: uuid.UUID,
                            action: str, actor_id: uuid.UUID,
                            facility_id: uuid.UUID,
                            old_value: dict | None = None,
                            new_value: dict | None = None,
                            reason: str | None = None) -> None:
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
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
