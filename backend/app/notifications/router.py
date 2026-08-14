"""notifications module router — endpoints land here; see this module's GitHub issues."""
import json 
import uuid
from datetime import datetime, timezone
 
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.redis import department_channel, facility_channel, subscribe
from app.departments.models import Department
from app.notifications.models import NotificationHistory
from app.notifications import service
from app.notifications.schemas import NotificationHistoryListOut, NotificationHistoryOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


_STAFF_ROLES = ("doctor", "nurse", "lab_tech", "pharmacist", "radiology_tech", "hod", "admin")
_HISTORY_ROLES = ("hod", "admin")

 
@router.get("/ping")
async def ping() -> dict:
    return {"module": "notifications", "status": "stub"}


def _format_sse(event_id: str, event_type: str, payload: dict) -> str:
    data = json.dumps({"event_type": event_type, "payload": payload})
    return f"id: {event_id}\ndata: {data}\n\n"


async def _catch_up_department_events(
    db: AsyncSession, department_id: uuid.UUID, last_event_id: str | None
) -> list[NotificationHistory]:
    query = select(NotificationHistory).where(NotificationHistory.department_id == department_id)
    if last_event_id:
        try:
            since = datetime.fromisoformat(last_event_id)
            query = query.where(NotificationHistory.created_at > since)
        except ValueError:
            pass
    query = query.order_by(NotificationHistory.created_at.asc())
    result = await db.execute(query)
    return list(result.scalars().all())
 
 
# ---------------- STAFF ALERTS: DEPARTMENT-SCOPED SSE STREAM ----------------
@router.get(
    "/stream/department/{department_id}",
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def department_notification_stream(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Live staff alerts for one department, with reconnect catch-up.

    A browser's EventSource automatically sends back Last-Event-ID after
    any disconnect -- we use that to replay anything missed from
    notification_history before switching to live Redis delivery.
    """
    department = await db.get(Department, department_id)
    if department is None or department.facility_id != current_db_user.facility_id:
        raise HTTPException(404, "Department not found")

    missed = await _catch_up_department_events(db, department_id, last_event_id)
    channel = department_channel(department_id)
 
    async def event_stream():
        for row in missed:
            yield _format_sse(row.created_at.isoformat(), row.event_type, row.payload)

        async with subscribe(channel) as pubsub:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                event = json.loads(message["data"])
                event_id = datetime.now(timezone.utc).isoformat()
                yield _format_sse(event_id, event["event_type"], event["payload"])
 
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
 
 
# ---------------- STAFF ALERTS: FACILITY-WIDE SSE STREAM ----------------
@router.get(
    "/stream/facility/{facility_id}",
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def facility_notification_stream(
    facility_id: uuid.UUID,
    current_db_user: CurrentDbUser, 
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Live facility-wide staff alerts (e.g. blood bank supply issues)."""
    if facility_id != current_db_user.facility_id:
        raise HTTPException(404, "Facility not found")
 
    channel = facility_channel(facility_id)
 
    async def event_stream():
        async with subscribe(channel) as pubsub:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                yield f"data: {message['data']}\n\n"
 
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
 
 
# ---------------- NOTIFICATION HISTORY: LIST (hod/admin only) ----------------
@router.get(
    "/history",
    dependencies=[Depends(require_roles(*_HISTORY_ROLES))],
)
async def list_notification_history(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    department_id: uuid.UUID | None = None,
    event_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("-created_at"),
) -> dict:
    result = await service.list_notification_history(
        db,
        caller_facility_id=current_db_user.facility_id,
        department_id=department_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    return NotificationHistoryListOut(
        items=[NotificationHistoryOut.model_validate(item) for item in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
    ).model_dump(mode="json")
 