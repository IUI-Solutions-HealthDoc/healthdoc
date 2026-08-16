"""queue module router — create queue, token generation, admin call-next
override, force-complete override, priority elevation, listing.
 
Doctors have no endpoints here — finishing a prescription/order elsewhere
triggers the automatic advance via service.complete_by_visit_id(). Admin
keeps manual overrides for edge cases.
"""
import uuid
from datetime import date 

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.deps import AuditActor, get_current_actor_dependency
from app.auth.deps import CurrentDbUser, CurrentUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.common.redis import publish_event, queue_channel, subscribe
from app.queue import service
from app.queue.schemas import (
    CompleteAdvanceOut,
    HodDashboardOverviewOut,
    QueueCreate,
    QueueOut,
    QueueTokenGenerateRequest,
    QueueTokenListItemOut,
    QueueTokenListOut,
    QueueTokenOut,
    RosterAvailabilityUpdate,
    RosterCreate,
    RosterOut,
    TokenPriorityElevate,
    PendingLabOrderOut,
    TokenReassign,
    DepartmentWorkloadOut,
    EmergencyEscalationOut,
)

router = APIRouter(prefix="/queue", tags=["queue"])


# ---------------- CREATE QUEUE ----------------
@router.post(
    "/queues",
    status_code=201,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def create_queue(
    payload: QueueCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    caller_facility_id = current_db_user.facility_id
    queue = await service.create_queue(
        db,
        department_id=payload.department_id,
        doctor_user_id=payload.doctor_user_id,
        room_id=payload.room_id,
        display_label=payload.display_label,
        service_date=payload.service_date,
        caller_facility_id=caller_facility_id,
    )
    return QueueOut.model_validate(queue).model_dump(mode="json")


# ---------------- CREATE TOKEN ----------------
_CREATE_TOKEN_ENDPOINT = "POST /queue/tokens"


@router.post(
    "/tokens",
    status_code=201,
    dependencies=[Depends(require_roles("receptionist", "nurse", "emergency", "admin"))],
)
async def create_token(
    payload: QueueTokenGenerateRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
 
    caller_user_id, caller_facility_id, _caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
 
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _CREATE_TOKEN_ENDPOINT, request_hash, caller_user_id
    )
    if existing is not None:
        return existing.response_body
 
    token = await service.create_token(
        db,
        queue_id=payload.queue_id,
        visit_id=payload.visit_id,
        priority=payload.priority,
        caller_facility_id=caller_facility_id,
    )
    response_body = QueueTokenOut.model_validate(token).model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _CREATE_TOKEN_ENDPOINT, 201, response_body,
        user_id=caller_user_id,
    )
    return response_body


# ---------------- ADMIN MANUAL OVERRIDE: CALL NEXT ----------------
@router.post(
    "/tokens/{queue_id}/call-next",
    dependencies=[Depends(require_roles("admin"))],
)

async def call_next(
    queue_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    caller_facility_id = current_db_user.facility_id
    token, pending_event = await service.call_next_token(db, queue_id, caller_facility_id)
    if pending_event is not None:
        background_tasks.add_task(
            publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
        )
    return QueueTokenOut.model_validate(token).model_dump(mode="json")

# ---------------- ADMIN MANUAL OVERRIDE: FORCE-COMPLETE ----------------
@router.post(
    "/tokens/{token_id}/complete",
    dependencies=[Depends(require_roles("admin"))],
)
async def force_complete_token(
    token_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    caller_facility_id = current_db_user.facility_id
    completed_token, next_token, pending_event = await service.admin_force_complete(
        db, token_id, caller_facility_id
    )
    if pending_event is not None:
        background_tasks.add_task(
            publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
        )
    return CompleteAdvanceOut(
        completed_token=QueueTokenOut.model_validate(completed_token),
        next_token=QueueTokenOut.model_validate(next_token) if next_token else None,
    ).model_dump(mode="json")

# ---------------- PRIORITY ELEVATION ----------------
@router.patch(
    "/tokens/{token_id}/priority",
    dependencies=[Depends(require_roles("receptionist", "doctor", "emergency", "hod"))],
)
async def elevate_priority(
    token_id: uuid.UUID,
    payload: TokenPriorityElevate,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    caller_facility_id = current_db_user.facility_id
    token = await service.elevate_priority(
        db,
        token_id,
        payload.priority,
        payload.reason,
        caller_sub=user.sub,
        caller_roles=user.roles,
        caller_amr=user.amr,
        caller_facility_id=caller_facility_id,
    )
    return QueueTokenOut.model_validate(token).model_dump(mode="json")


# ---------------- LIST QUEUE TOKENS ----------------
@router.get(
    "/queues/{queue_id}/tokens",
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def list_queue_tokens(
    queue_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    caller_facility_id = current_db_user.facility_id
    result = await service.list_queue_tokens(db, queue_id, caller_facility_id)
    return QueueTokenListOut(
        waiting_count=result["waiting_count"],
        now_serving=result["now_serving"],
        items=[QueueTokenListItemOut(**item) for item in result["items"]],
    ).model_dump(mode="json")


# ---------------- PUBLIC DISPLAY -- SSE STREAM ----------------  # <<< NEW: everything below this line
# No require_roles / no CurrentUser here on purpose: this is the OPD wall
# screen, which has no login. Payload reaching this endpoint is already
# PII-free (token/doctor/room only) -- built that way in service.py's
# _advance_queue(), not filtered here.
@router.get("/display/{department_id}/stream")
async def queue_display_stream(department_id: uuid.UUID, request: Request) -> StreamingResponse:
    """
    Streams live queue-display events for one department as
    Server-Sent Events. A browser (or a dumb TV browser) opens this once
    and receives a new "data: ..." line every time call-next publishes
    a token_called event for this department.
 
    Rate limiting, the 5s cache, and per-IP connection caps described in
    schema doc §4A.7 are nginx-level concerns (infra/), not handled here.
 
    Disconnect detection is currently blocked by a known bug in
    EnvelopeMiddleware (BaseHTTPMiddleware incompatible with streaming
    responses) -- confirmed, not yet fixed as of this commit. The
    polling logic below is correct and will start working once that's
    resolved; no changes needed here when it is.
    """
    channel = queue_channel(department_id)
 
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
# ---------------- ROSTER: CREATE (hod/admin only) ----------------
@router.post(
    "/rosters",
    status_code=201,
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def create_roster_entry(
    payload: RosterCreate,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    _caller_user_id, _caller_facility_id, caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
    entry = await service.create_roster_entry(
        db,
        staff_user_id=payload.staff_user_id,
        department_id=payload.department_id,
        room_id=payload.room_id,
        shift=payload.shift,
        roster_date=payload.roster_date,
        caller_facility_id=current_db_user.facility_id,
        caller_roles=current_db_user.roles,
        caller_department_id=caller_department_id,
    )
    return RosterOut.model_validate(entry).model_dump(mode="json")
 
 
# ---------------- ROSTER: LIST ----------------
@router.get(
    "/rosters",
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "hod", "admin"))],
)
async def list_roster(
    department_id: uuid.UUID,
    roster_date: date,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entries = await service.list_roster(db, department_id, roster_date, current_db_user.facility_id)
    return {"items": [RosterOut.model_validate(e).model_dump(mode="json") for e in entries]}
 
 
# ---------------- ROSTER: AVAILABILITY (hod/admin only) ----------------
@router.patch(
    "/rosters/{roster_id}/availability",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def update_roster_availability(
    roster_id: uuid.UUID,
    payload: RosterAvailabilityUpdate,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    _caller_user_id, _caller_facility_id, caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
    entry, pending_event = await service.update_roster_availability(
        db,
        roster_id=roster_id,
        is_available=payload.is_available,
        caller_facility_id=current_db_user.facility_id,
        caller_roles=current_db_user.roles,
        caller_department_id=caller_department_id,
    )
    if pending_event is not None:
        background_tasks.add_task(
            publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
        )
    return RosterOut.model_validate(entry).model_dump(mode="json")
 
 
# ---------------- QUEUE: PAUSE (hod/admin only) ----------------
@router.post(
    "/queues/{queue_id}/pause",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def pause_queue(
    queue_id: uuid.UUID,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    _caller_user_id, _caller_facility_id, caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
    queue, pending_event = await service.pause_queue(
        db, queue_id, current_db_user.facility_id, current_db_user.roles, caller_department_id
    )
    if pending_event is not None:
        background_tasks.add_task(
            publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
        )
    return QueueOut.model_validate(queue).model_dump(mode="json")
 
 
# ---------------- QUEUE: RESUME (hod/admin only) ----------------
@router.post(
    "/queues/{queue_id}/resume",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def resume_queue(
    queue_id: uuid.UUID,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    _caller_user_id, _caller_facility_id, caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
    queue, pending_event = await service.resume_queue(
        db, queue_id, current_db_user.facility_id, current_db_user.roles, caller_department_id
    )
    if pending_event is not None:
        background_tasks.add_task(
            publish_event, pending_event["channel"], pending_event["event_type"], pending_event["payload"]
        )
    return QueueOut.model_validate(queue).model_dump(mode="json")


# ---------------- HOD DASHBOARD: OVERVIEW ----------------
@router.get(
    "/hod-dashboard/{department_id}",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def get_hod_dashboard_overview(
    department_id: uuid.UUID,
    overview_date: date,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    overview = await service.get_hod_dashboard_overview(
        db, department_id, overview_date, current_db_user.facility_id
    )
    return HodDashboardOverviewOut(**overview).model_dump(mode="json")


# ---------------- HOD DASHBOARD: PENDING LAB ORDERS ----------------
@router.get(
    "/hod-dashboard/{department_id}/pending-lab-orders",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def get_pending_lab_orders(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = await service.get_pending_lab_orders(db, department_id, current_db_user.facility_id)
    return {"items": [PendingLabOrderOut(**item).model_dump(mode="json") for item in items]}


# ---------------- HOD DASHBOARD: REASSIGN TOKEN (hod/admin only) ----------------
@router.post(
    "/tokens/{token_id}/reassign",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def reassign_token(
    token_id: uuid.UUID,
    payload: TokenReassign,
    user: CurrentUser,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    _caller_user_id, _caller_facility_id, caller_department_id = await service.resolve_caller_full_context(
        db, user.sub
    )
    new_token = await service.reassign_token(
        db,
        token_id=token_id,
        target_queue_id=payload.target_queue_id,
        caller_facility_id=current_db_user.facility_id,
        caller_roles=current_db_user.roles,
        caller_department_id=caller_department_id,
    )
    return QueueTokenOut.model_validate(new_token).model_dump(mode="json")


# ---------------- HOD DASHBOARD: DEPARTMENT WORKLOAD ----------------
@router.get(
    "/hod-dashboard/{department_id}/workload",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def get_department_workload(
    department_id: uuid.UUID,
    workload_date: date,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    workload = await service.get_department_workload(
        db, department_id, workload_date, current_db_user.facility_id
    )
    return DepartmentWorkloadOut(**workload).model_dump(mode="json")


# ---------------- HOD DASHBOARD: EMERGENCY ESCALATIONS ----------------
@router.get(
    "/hod-dashboard/{department_id}/emergency-escalations",
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def get_emergency_escalations(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    escalations = await service.get_emergency_escalations(db, department_id, current_db_user.facility_id)
    return {"items": [EmergencyEscalationOut(**item).model_dump(mode="json") for item in escalations]}
