"""Notification event preparation for staff-facing SSE alerts.

    pending_event = await prepare_lab_report_ready_event(db, ...)
    await db.commit()
    background_tasks.add_task(
        publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
    )
"""
import uuid

from fastapi import HTTPException 
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.common.redis import department_channel, facility_channel
from app.notifications.models import NotificationHistory
from sqlalchemy import desc, select, func
 
 
async def prepare_lab_report_ready_event(
    db: AsyncSession,
    facility_id: uuid.UUID,
    department_id: uuid.UUID,
    lab_order_item_id: uuid.UUID,
    accession_number: str,
    doctor_user_id: uuid.UUID,
    test_name: str,
) -> dict:
    payload = {
        "department_id": str(department_id),
        "lab_order_item_id": str(lab_order_item_id),
        "accession_number": accession_number,
        "doctor_user_id": str(doctor_user_id),
        "test_name": test_name,
    }
    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type="lab_report_ready",
        payload=payload,
        department_id=department_id,
        facility_id=facility_id,
    ))
    await db.flush()
    return {
        "channel": department_channel(department_id),
        "event_type": "lab_report_ready",
        "payload": payload,
    }
 
 
async def prepare_critical_value_alert_event(
    db: AsyncSession,
    facility_id: uuid.UUID,
    department_id: uuid.UUID,
    lab_order_item_id: uuid.UUID,
    accession_number: str,
    doctor_user_id: uuid.UUID,
    test_name: str,
    value: str,
    severity: str,
) -> dict:
    payload = {
        "department_id": str(department_id),
        "lab_order_item_id": str(lab_order_item_id),
        "accession_number": accession_number,
        "doctor_user_id": str(doctor_user_id),
        "test_name": test_name,
        "value": value,
        "severity": severity,
    }
    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type="critical_value_alert",
        payload=payload,
        department_id=department_id,
        facility_id=facility_id,
    ))
    await db.flush()
    return {
        "channel": department_channel(department_id),
        "event_type": "critical_value_alert",
        "payload": payload,
    }
 
 
async def prepare_low_stock_alert_event(
    db: AsyncSession,
    facility_id: uuid.UUID,
    item_id: uuid.UUID,
    item_name: str,
    current_quantity: str,
    reorder_level: str,
    department_id: uuid.UUID | None = None,
) -> dict:
    payload = {
        "item_id": str(item_id),
        "item_name": item_name,
        "current_quantity": current_quantity,
        "reorder_level": reorder_level,
    }
    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type="low_stock_alert",
        payload=payload,
        department_id=department_id,
        facility_id=facility_id,
    ))
    await db.flush()
 
    channel = department_channel(department_id) if department_id else facility_channel(facility_id)
    return {
        "channel": channel,
        "event_type": "low_stock_alert",
        "payload": payload,
    }


_MAX_PAGE_SIZE = 100
_SORTABLE_FIELDS = {"created_at": NotificationHistory.created_at}
 
 
# ---------------- NOTIFICATION HISTORY: LIST (hod/admin only) ----------------
async def list_notification_history(
    db: AsyncSession,
    caller_facility_id: uuid.UUID,
    department_id: uuid.UUID | None,
    event_type: str | None,
    page: int,
    page_size: int,
    sort: str,
) -> dict:
    if page_size > _MAX_PAGE_SIZE:
        raise HTTPException(422, f"page_size cannot exceed {_MAX_PAGE_SIZE}")
 
    descending = sort.startswith("-")
    field_name = sort[1:] if descending else sort
    if field_name not in _SORTABLE_FIELDS:
        raise HTTPException(422, f"Cannot sort by '{field_name}' -- allowed: {sorted(_SORTABLE_FIELDS)}")
    sort_column = _SORTABLE_FIELDS[field_name]
    sort_column = desc(sort_column) if descending else sort_column
 
    query = select(NotificationHistory).where(NotificationHistory.facility_id == caller_facility_id)
    count_query = select(func.count(NotificationHistory.id)).where(
        NotificationHistory.facility_id == caller_facility_id
    )
 
    if department_id is not None:
        query = query.where(NotificationHistory.department_id == department_id)
        count_query = count_query.where(NotificationHistory.department_id == department_id)
 
    if event_type is not None:
        query = query.where(NotificationHistory.event_type == event_type)
        count_query = count_query.where(NotificationHistory.event_type == event_type)
 
    total = (await db.execute(count_query)).scalar_one()
 
    query = query.order_by(sort_column).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(query)).scalars().all()
 
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
 