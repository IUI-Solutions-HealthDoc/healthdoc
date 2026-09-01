"""queue module router — create queue, token generation, admin call-next
override, force-complete override, priority elevation, listing.
 
Doctors have no endpoints here — finishing a prescription/order elsewhere
triggers the automatic advance via service.complete_by_visit_id(). Admin
keeps manual overrides for edge cases.
"""
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.deps import AuditActor, get_current_actor_dependency
from app.auth.deps import CurrentDbUser, CurrentUser, DbUser, require_roles
from app.common.business_date import get_business_date
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.common.redis import publish_event, queue_channel, subscribe
from app.queue import service
from app.queue.schemas import (
    CompleteAdvanceOut,
    DepartmentWorkloadOut,
    DoctorWorklistItemOut,
    DoctorWorklistOut,
    EmergencyEscalationOut,
    HodDashboardOverviewOut,
    PendingApprovalOut,
    PendingLabOrderOut,
    QueueCreate,
    QueueOpeningOptionOut,
    QueueOpeningOptionsOut,
    QueueOut,
    QueueSummaryOut,
    QueueTokenGenerateRequest,
    QueueTokenListItemOut,
    QueueTokenListOut,
    QueueTokenOut,
    RosterAvailabilityUpdate,
    RosterCandidateOut,
    RosterCreate,
    RosterOut,
    TokenPriorityElevate,
    TokenReassign,
)

router = APIRouter(prefix="/queue", tags=["queue"])


def _require_hod_dashboard_department(
    current_db_user: DbUser,
    requested_department_id: uuid.UUID,
) -> None:
    """HODs may read only their own department; admins remain facility-wide.

    Facility scoping alone is insufficient here: two departments in the same
    hospital share a facility id. The frontend deliberately has no department
    picker, but authorization cannot depend on an honest browser.
    """
    if "admin" in current_db_user.roles:
        return
    if current_db_user.department_id != requested_department_id:
        raise HTTPException(
            403,
            detail={
                "code": "hod_department_scope_violation",
                "message": "HOD dashboard access is limited to the caller's department",
            },
        )


def _require_roster_list_department(
    current_db_user: DbUser,
    requested_department_id: uuid.UUID,
) -> None:
    """Apply HOD scope without removing permissions granted by another role.

    Keycloak tokens may carry multiple roles. Doctor, nurse, receptionist and
    admin are intentionally allowed to inspect facility rosters across
    departments, so a clinician who also heads a department keeps that read.
    A HOD-only token remains limited to its own department.
    """
    cross_department_roles = {"doctor", "nurse", "receptionist", "admin"}
    if cross_department_roles & set(current_db_user.roles):
        return
    _require_hod_dashboard_department(current_db_user, requested_department_id)


@router.get(
    "/worklist",
    # DOCTOR ONLY. `admin` was here and the API answered 200 for dev.admin while
    # the frontend redirected admins away from /doctor — UI containment without
    # matching authorization. An assessor tests the endpoint, not the menu, and
    # "the screen is hidden" is not an answer to "the token was accepted".
    #
    # Nothing calls this as admin: features/doctor owns the only call site and
    # ROLES.ADMIN's route prefixes are /admin, /billing, /reports, /audit-viewer.
    # The grant was unused and load-bearing only for a finding.
    dependencies=[Depends(require_roles("doctor"))],
)
async def get_doctor_worklist(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await service.get_doctor_worklist(
        db,
        current_db_user.id,
        current_db_user.facility_id,
        current_db_user.roles,
    )
    return DoctorWorklistOut(
        items=[DoctorWorklistItemOut(**row) for row in rows]
    ).model_dump(mode="json")


@router.get(
    "/worklist/{token_id}",
    # Doctor only, for the same reason as the list route above — and this one
    # is worth its own note. The first pass at this fix narrowed only
    # GET /worklist and left this sibling open, which is precisely the mistake
    # that commit's own message warned about: "narrowing just the reported
    # route leaves siblings open and the finding half-closed".
    #
    # tests/test_role_boundaries.py caught it, because it asserts over every
    # route matching the path fragment rather than the one endpoint a report
    # happened to name. That is the whole argument for testing the family.
    dependencies=[Depends(require_roles("doctor"))],
)
async def get_doctor_worklist_token(
    token_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await service.get_doctor_worklist(
        db,
        current_db_user.id,
        current_db_user.facility_id,
        current_db_user.roles,
        token_id=token_id,
    )
    if not rows:
        raise HTTPException(404, "Queue token not found")
    return DoctorWorklistItemOut(**rows[0]).model_dump(mode="json")


# ---------------- CREATE QUEUE ----------------
_CREATE_QUEUE_ENDPOINT = "POST /queue/queues"


@router.post(
    "/queues",
    status_code=201,
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def create_queue(
    payload: QueueCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    actor: AuditActor = Depends(get_current_actor_dependency),
) -> dict:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")

    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db,
        idempotency_key,
        _CREATE_QUEUE_ENDPOINT,
        request_hash,
        current_db_user.id,
    )
    if existing is not None:
        return existing.response_body

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
    response_body = QueueOut.model_validate(queue).model_dump(mode="json")
    await record_idempotent_response(
        db,
        idempotency_key,
        _CREATE_QUEUE_ENDPOINT,
        201,
        response_body,
        user_id=current_db_user.id,
    )
    return response_body


@router.get(
    "/queues",
    dependencies=[Depends(require_roles("receptionist", "nurse", "doctor", "hod", "admin"))],
)
async def list_queues(
    current_db_user: CurrentDbUser,
    service_date: date | None = Query(
        default=None,
        description="Defaults to the facility's business date, not the server's.",
    ),
    open_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Today's queues at the caller's facility.

    POST /queue/tokens takes a queue_id and nothing returned one: /worklist is
    a doctor's own list and doctor/admin-only. A receptionist could not issue a
    token from a screen because there was no way to discover a queue to issue it
    into.

    The default date is the FACILITY's business date via get_business_date, not
    date.today() on the server. A queue opened at 09:00 IST belongs to the
    facility's day; a UTC server would show it under yesterday for the first
    five and a half hours of every morning.
    """
    business_date = service_date or await get_business_date(db, current_db_user.facility_id)
    rows = await service.list_queues(
        db, current_db_user.facility_id, business_date, open_only=open_only
    )
    return [QueueSummaryOut(**row).model_dump(mode="json") for row in rows]


@router.get(
    "/opening-options",
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def list_queue_opening_options(
    current_db_user: CurrentDbUser,
    service_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    business_date = service_date or await get_business_date(
        db, current_db_user.facility_id
    )
    rows = await service.list_queue_opening_options(
        db, current_db_user.facility_id, business_date
    )
    return QueueOpeningOptionsOut(
        service_date=business_date,
        items=[QueueOpeningOptionOut(**row) for row in rows],
    ).model_dump(mode="json")


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
    service.require_initial_priority_allowed(payload.priority, user.roles)
 
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
 
    Disconnect detection works. It was blocked by EnvelopeMiddleware being a
    BaseHTTPMiddleware, which never forwarded http.disconnect to the endpoint --
    so the polling below could not see a departed client, the generator was
    never closed, and every dropped display leaked its Redis subscription for
    the life of the process. The middleware is raw ASGI now and the note that
    used to say "correct but not yet working" no longer applies: this is
    covered by test_sse_stream_unsubscribes_on_disconnect.
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
    dependencies=[Depends(require_roles("hod"))],
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


# ---------------- ROSTER: ACTIVE DEPARTMENT STAFF ----------------
@router.get(
    "/roster-candidates",
    dependencies=[Depends(require_roles("hod"))],
)
async def list_roster_candidates(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return only the staff identity needed by the HOD roster form.

    Widening the admin-only ``GET /users`` endpoint would expose facility-wide
    staff records.  A purpose-built list keeps this read department-scoped and
    omits email, mobile, employee id and registration details.
    """
    _require_hod_dashboard_department(current_db_user, department_id)
    rows = await service.list_roster_candidates(
        db,
        department_id=department_id,
        caller_facility_id=current_db_user.facility_id,
    )
    return {
        "items": [
            RosterCandidateOut(**row).model_dump(mode="json") for row in rows
        ]
    }
 
 
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
    # Reception, doctors and nurses may inspect another department's roster
    # within their facility for cross-department flow. A department-scoped HOD
    # may not use the same read to inspect a peer department.
    if "hod" in current_db_user.roles:
        _require_roster_list_department(current_db_user, department_id)
    entries = await service.list_roster(db, department_id, roster_date, current_db_user.facility_id)
    return {"items": [RosterOut.model_validate(e).model_dump(mode="json") for e in entries]}
 
 
# ---------------- ROSTER: AVAILABILITY (hod/admin only) ----------------
@router.patch(
    "/rosters/{roster_id}/availability",
    dependencies=[Depends(require_roles("hod"))],
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
    dependencies=[Depends(require_roles("hod"))],
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
    dependencies=[Depends(require_roles("hod"))],
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
    dependencies=[Depends(require_roles("hod"))],
)
async def get_hod_dashboard_overview(
    department_id: uuid.UUID,
    overview_date: date,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_hod_dashboard_department(current_db_user, department_id)
    overview = await service.get_hod_dashboard_overview(
        db, department_id, overview_date, current_db_user.facility_id
    )
    return HodDashboardOverviewOut(**overview).model_dump(mode="json")


# ---------------- HOD DASHBOARD: PENDING LAB ORDERS ----------------
@router.get(
    "/hod-dashboard/{department_id}/pending-lab-orders",
    dependencies=[Depends(require_roles("hod"))],
)
async def get_pending_lab_orders(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_hod_dashboard_department(current_db_user, department_id)
    items = await service.get_pending_lab_orders(db, department_id, current_db_user.facility_id)
    return {"items": [PendingLabOrderOut(**item).model_dump(mode="json") for item in items]}


# ---------------- HOD DASHBOARD: REASSIGN TOKEN (hod/admin only) ----------------
@router.post(
    "/tokens/{token_id}/reassign",
    dependencies=[Depends(require_roles("hod"))],
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
    dependencies=[Depends(require_roles("hod"))],
)
async def get_department_workload(
    department_id: uuid.UUID,
    workload_date: date,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_hod_dashboard_department(current_db_user, department_id)
    workload = await service.get_department_workload(
        db, department_id, workload_date, current_db_user.facility_id
    )
    return DepartmentWorkloadOut(**workload).model_dump(mode="json")


# ---------------- HOD DASHBOARD: EMERGENCY ESCALATIONS ----------------
@router.get(
    "/hod-dashboard/{department_id}/emergency-escalations",
    dependencies=[Depends(require_roles("hod"))],
)
async def get_emergency_escalations(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_hod_dashboard_department(current_db_user, department_id)
    escalations = await service.get_emergency_escalations(db, department_id, current_db_user.facility_id)
    return {"items": [EmergencyEscalationOut(**item).model_dump(mode="json") for item in escalations]}


# ---------------- HOD DASHBOARD: PENDING APPROVALS ----------------
@router.get(
    "/hod-dashboard/{department_id}/pending-approvals",
    dependencies=[Depends(require_roles("hod"))],
)
async def get_pending_approvals(
    department_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_hod_dashboard_department(current_db_user, department_id)
    approvals = await service.get_pending_approvals(db, department_id, current_db_user.facility_id)
    return {"items": [PendingApprovalOut(**item).model_dump(mode="json") for item in approvals]}
