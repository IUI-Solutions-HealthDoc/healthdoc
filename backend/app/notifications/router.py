"""notifications module router — endpoints land here; see this module's GitHub issues."""
import json 
import uuid
from datetime import datetime, timezone
 
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import SessionLocal, get_db
from app.common.redis import department_channel, facility_channel, subscribe
from app.departments.models import Department
from app.notifications.models import NotificationHistory
from app.notifications import service
from app.notifications.schemas import (
    NotificationHistoryListOut, NotificationHistoryOut,
    NotificationPreferenceOut, NotificationPreferenceSet,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


_STAFF_ROLES = ("doctor", "nurse", "lab_tech", "pharmacist", "radiology_tech", "hod", "admin")
_HISTORY_ROLES = ("hod", "admin")

 
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
 

 # ---------------- Publish-path preference gate ----------------
async def _filter_by_preferences(
    db: AsyncSession, *, facility_id: uuid.UUID, roles: list[str], rows: list[NotificationHistory]
) -> list[NotificationHistory]:
    """Drop rows silenced for every role the caller holds (#400).
 
    Reconnect catch-up is a one-shot batch computed before streaming starts,
    so it's fine to do this with the request's own db session -- unlike the
    live loop below, nothing here is held open for the life of the SSE
    connection.
    """
    if not roles:
        return rows
    silenced_per_role = [
        await service.silenced_event_types(db, facility_id=facility_id, role=role)
        for role in roles
    ]
    suppressed = set.intersection(*silenced_per_role)  # silenced by every role -> suppress
    if not suppressed:
        return rows
    return [row for row in rows if row.event_type not in suppressed]
 
 
async def _event_visible(*, facility_id: uuid.UUID, roles: list[str], event_type: str) -> bool:
    """Live-path preference check, always up to date."""
    async with SessionLocal() as short_session:
        return await service.is_enabled_for_any_roles(
            short_session, facility_id=facility_id, roles=roles, event_type=event_type
        )
 
 
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
    # don't replay events silenced for every role the caller holds.
    missed = await _filter_by_preferences(
        db, facility_id=current_db_user.facility_id, roles=current_db_user.roles, rows=missed
    )
    channel = department_channel(department_id)
    facility_id = current_db_user.facility_id
    roles = current_db_user.roles
 
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
                # gate live events the same way as catch-up.
                if not await _event_visible(
                    facility_id=facility_id, roles=roles, event_type=event["event_type"]
                ):
                    continue
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
    roles = current_db_user.roles

    async def event_stream():
        async with subscribe(channel) as pubsub:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                event = json.loads(message["data"])
                if not await _event_visible(
                    facility_id=facility_id, roles=roles, event_type=event["event_type"]
                ):
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
 

# ------------------------Per-role preferences --------------------
#
# #230 shipped the history API; preferences never existed, so every notification
# reached everyone entitled to it with no way to silence a category for a role.
#
# Reads are open to any staff role (you may see what is configured for you);
# writes are admin/hod only, because silencing an event type for a whole role at
# a facility is a decision with clinical consequences.

@router.get(
    "/preferences",
    response_model=list[NotificationPreferenceOut],
    dependencies=[Depends(require_roles(*_STAFF_ROLES))],
)
async def list_notification_preferences(
    current_db_user: CurrentDbUser,
    role: str | None = Query(default=None, description="Filter to one role."),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationPreferenceOut]:
    """What is silenced at the caller's facility.

    Only rows that exist are returned, and a row exists only where someone made
    a deliberate decision — anything absent is enabled.
    """
    rows = await service.list_preferences(
        db, facility_id=current_db_user.facility_id, role=role)
    return [NotificationPreferenceOut.model_validate(r) for r in rows]


@router.put(
    "/preferences",
    response_model=NotificationPreferenceOut,
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def set_notification_preference(
    payload: NotificationPreferenceSet,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceOut:
    """Silence or re-enable one event_type for one role at the caller's facility.

    PUT rather than POST: the unique key is (facility, role, event_type), so
    this is idempotent by construction — sending the same decision twice leaves
    the same single row.

    Scoped to the caller's own facility. An admin at one hospital must not be
    able to silence critical alerts at another.
    """
    pref = await service.set_preference(
        db,
        facility_id=current_db_user.facility_id,
        role=payload.role,
        event_type=payload.event_type,
        enabled=payload.enabled,
        actor_id=current_db_user.id,
    )
    return NotificationPreferenceOut.model_validate(pref)
