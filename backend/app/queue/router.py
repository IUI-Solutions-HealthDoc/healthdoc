"""queue module router — endpoints land here; see this module's GitHub issues."""
"""queue module router — create queue, token generation, admin call-next
override, force-complete override, priority elevation, listing.

Doctors have no endpoints here — finishing a prescription/order elsewhere
triggers the automatic advance via service.complete_by_visit_id(). Admin
keeps manual overrides for edge cases.
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.common.db import get_db
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
async def create_queue(payload: QueueCreate, db: AsyncSession = Depends(get_db)) -> dict:
    queue = await service.create_queue(
        db,
        department_id=payload.department_id,
        doctor_user_id=payload.doctor_user_id,
        room_id=payload.room_id,
        display_label=payload.display_label,
        service_date=payload.service_date,
    )
    return QueueOut.model_validate(queue).model_dump(mode="json")


# ---------------- CREATE TOKEN ----------------
@router.post(
    "/tokens",
    status_code=201,
    dependencies=[Depends(require_roles("receptionist", "nurse", "emergency", "admin"))],
)
async def create_token(
    payload: QueueTokenGenerateRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    token = await service.create_token(
        db,
        queue_id=payload.queue_id,
        visit_id=payload.visit_id,
        priority=payload.priority,
    )
    return QueueTokenOut.model_validate(token).model_dump(mode="json")


# ---------------- ADMIN MANUAL OVERRIDE: CALL NEXT ----------------
@router.post(
    "/tokens/{queue_id}/call-next",
    dependencies=[Depends(require_roles("admin"))],
)
async def call_next(queue_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    token = await service.call_next_token(db, queue_id)
    return QueueTokenOut.model_validate(token).model_dump(mode="json")


# ---------------- ADMIN MANUAL OVERRIDE: FORCE-COMPLETE ----------------
@router.post(
    "/tokens/{token_id}/complete",
    dependencies=[Depends(require_roles("admin"))],
)
async def force_complete_token(token_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    completed_token, next_token = await service.admin_force_complete(db, token_id)
    return CompleteAdvanceOut(
        completed_token=QueueTokenOut.model_validate(completed_token),
        next_token=QueueTokenOut.model_validate(next_token) if next_token else None,
    ).model_dump(mode="json")


# ---------------- PRIORITY ELEVATION ----------------
@router.patch(
    "/tokens/{token_id}/priority",
    dependencies=[Depends(require_roles("receptionist", "admin"))],
)
async def elevate_priority(
    token_id: uuid.UUID, payload: TokenPriorityElevate, db: AsyncSession = Depends(get_db)
) -> dict:
    token = await service.elevate_priority(db, token_id, payload.priority)
    return QueueTokenOut.model_validate(token).model_dump(mode="json")


# ---------------- LIST QUEUE TOKENS ----------------
@router.get(
    "/queues/{queue_id}/tokens",
    dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))],
)
async def list_queue_tokens(queue_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    result = await service.list_queue_tokens(db, queue_id)
    return QueueTokenListOut(
        waiting_count=result["waiting_count"],
        now_serving=result["now_serving"],
        items=[QueueTokenListItemOut(**item) for item in result["items"]],
    ).model_dump(mode="json")