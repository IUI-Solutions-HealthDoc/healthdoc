"""queue module router — create queue, token generation, admin call-next
override, force-complete override, priority elevation, listing.
 
Doctors have no endpoints here — finishing a prescription/order elsewhere
triggers the automatic advance via service.complete_by_visit_id(). Admin
keeps manual overrides for edge cases.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.deps import AuditActor, get_current_actor_dependency
from app.auth.deps import CurrentDbUser, CurrentUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.common.redis import publish_event
from app.queue import service
from app.queue.schemas import (
    CompleteAdvanceOut,
    QueueCreate,
    QueueOut,
    QueueTokenGenerateRequest,
    QueueTokenListItemOut,
    QueueTokenListOut,
    QueueTokenOut,
    TokenPriorityElevate,
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
