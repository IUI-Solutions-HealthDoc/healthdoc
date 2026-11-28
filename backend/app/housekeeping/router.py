"""Housekeeping: room and bed cleaning tasks.

Bed turnovers arrive on their own from discharge and transfer. Ward staff
raise the rest (a spill, a routine or isolation clean). Starting a task names
the cleaner; completing it records what was done and, for a bed turnover,
returns the bed to the vacant pool. Linen stripped during a clean can be sent
to the laundry from the same form.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Bed, Ward
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.housekeeping import service
from app.housekeeping.models import OPEN_STATUSES, TASK_PRIORITIES, TASK_TYPES, HousekeepingTask
from app.laundry.models import LINEN_ITEM_TYPES

_STAFF = ("nurse", "admin", "hod", "supervisor")

router = APIRouter(prefix="/housekeeping", tags=["housekeeping"], dependencies=[Depends(require_roles(*_STAFF))])

TaskType = Literal[TASK_TYPES]  # type: ignore[valid-type]
Priority = Literal[TASK_PRIORITIES]  # type: ignore[valid-type]
ItemType = Literal[LINEN_ITEM_TYPES]  # type: ignore[valid-type]


async def _idempotency_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key", "message": "Idempotency-Key header is required"})
    return idempotency_key


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})  # type: ignore[attr-defined]


class TaskCreate(BaseModel):
    ward_id: uuid.UUID
    bed_id: uuid.UUID | None = None
    task_type: TaskType
    priority: Priority = "routine"
    notes: str | None = Field(default=None, max_length=500)


class TaskStart(BaseModel):
    assigned_to_name: str | None = Field(default=None, max_length=120)


class LinenLine(BaseModel):
    item_type: ItemType
    quantity: int = Field(ge=1, le=1000)


class TaskComplete(BaseModel):
    assigned_to_name: str | None = Field(default=None, max_length=120)
    linen_changed: bool = False
    mattress_disinfected: bool = False
    surfaces_disinfected: bool = False
    waste_removed: bool = False
    notes: str | None = Field(default=None, max_length=500)
    #: Linen stripped here and sent to the laundry, if any.
    linen_items: list[LinenLine] = Field(default_factory=list, max_length=len(LINEN_ITEM_TYPES))
    linen_infected: bool = False


class TaskCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    ward_name: str | None = None
    bed_id: uuid.UUID | None
    bed_number: str | None = None
    task_type: str
    priority: str
    source: str
    status: str
    notes: str | None
    requested_at: datetime
    assigned_to_name: str | None
    started_at: datetime | None
    completed_at: datetime | None
    linen_changed: bool
    mattress_disinfected: bool
    surfaces_disinfected: bool
    waste_removed: bool
    linen_batch_id: uuid.UUID | None
    cancel_reason: str | None


async def _out(db: AsyncSession, task: HousekeepingTask) -> TaskOut:
    ward = await db.get(Ward, task.ward_id)
    bed = await db.get(Bed, task.bed_id) if task.bed_id else None
    return TaskOut.model_validate(task).model_copy(
        update={"ward_name": ward.name if ward else None, "bed_number": bed.bed_number if bed else None}
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    state: Literal["open", "closed"] = Query("open"),
    ward_id: uuid.UUID | None = Query(None),
) -> list[TaskOut]:
    stmt = select(HousekeepingTask, Ward.name, Bed.bed_number).join(Ward, Ward.id == HousekeepingTask.ward_id).outerjoin(
        Bed, Bed.id == HousekeepingTask.bed_id
    ).where(HousekeepingTask.facility_id == current_db_user.facility_id)
    if ward_id is not None:
        stmt = stmt.where(HousekeepingTask.ward_id == ward_id)
    if state == "open":
        # Urgent first, then oldest first: the bed waiting longest is the one a ward is short of.
        stmt = stmt.where(HousekeepingTask.status.in_(OPEN_STATUSES)).order_by(
            case((HousekeepingTask.priority == "urgent", 0), else_=1), HousekeepingTask.requested_at
        )
    else:
        stmt = stmt.where(HousekeepingTask.status.not_in(OPEN_STATUSES)).order_by(
            HousekeepingTask.completed_at.desc()
        ).limit(100)
    rows = (await db.execute(stmt)).all()
    return [
        TaskOut.model_validate(task).model_copy(update={"ward_name": ward_name, "bed_number": bed_number})
        for task, ward_name, bed_number in rows
    ]


async def _replay_or_none(db, key, endpoint, payload, user_id):
    request_hash = hash_request_body(payload)
    cached = await check_idempotency(db, key, endpoint, request_hash, user_id)
    return TaskOut.model_validate(cached.response_body) if cached is not None else None


@router.post("/tasks", status_code=201, response_model=TaskOut)
async def raise_task(
    payload: TaskCreate,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    endpoint = "POST /housekeeping/tasks"
    if (cached := await _replay_or_none(db, idempotency_key, endpoint, payload, current_db_user.id)) is not None:
        return cached
    try:
        task = await service.raise_task(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id, **payload.model_dump()
        )
    except service.HousekeepingError as exc:
        raise _refused(exc) from None
    out = await _out(db, task)
    await record_idempotent_response(db, idempotency_key, endpoint, 201, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/tasks/{task_id}/start", response_model=TaskOut)
async def start_task(
    task_id: uuid.UUID,
    payload: TaskStart,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    endpoint = f"POST /housekeeping/tasks/{task_id}/start"
    if (cached := await _replay_or_none(db, idempotency_key, endpoint, payload, current_db_user.id)) is not None:
        return cached
    try:
        task = await service.get_scoped(db, task_id, current_db_user.facility_id, lock=True)
        await service.start(db, task, user_id=current_db_user.id, assigned_to_name=payload.assigned_to_name)
    except service.HousekeepingError as exc:
        raise _refused(exc) from None
    out = await _out(db, task)
    await record_idempotent_response(db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: uuid.UUID,
    payload: TaskComplete,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    endpoint = f"POST /housekeeping/tasks/{task_id}/complete"
    if (cached := await _replay_or_none(db, idempotency_key, endpoint, payload, current_db_user.id)) is not None:
        return cached
    from app.laundry.service import LaundryError

    try:
        task = await service.get_scoped(db, task_id, current_db_user.facility_id, lock=True)
        await service.complete(
            db, task, user_id=current_db_user.id, assigned_to_name=payload.assigned_to_name,
            linen_changed=payload.linen_changed, mattress_disinfected=payload.mattress_disinfected,
            surfaces_disinfected=payload.surfaces_disinfected, waste_removed=payload.waste_removed,
            notes=payload.notes, linen_items=[(line.item_type, line.quantity) for line in payload.linen_items],
            linen_infected=payload.linen_infected,
        )
    except (service.HousekeepingError, LaundryError) as exc:
        raise _refused(exc) from None
    out = await _out(db, task)
    await record_idempotent_response(db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut, dependencies=[Depends(require_roles("nurse", "admin", "supervisor"))])
async def cancel_task(
    task_id: uuid.UUID,
    payload: TaskCancel,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    endpoint = f"POST /housekeeping/tasks/{task_id}/cancel"
    if (cached := await _replay_or_none(db, idempotency_key, endpoint, payload, current_db_user.id)) is not None:
        return cached
    try:
        task = await service.get_scoped(db, task_id, current_db_user.facility_id, lock=True)
        await service.cancel(db, task, user_id=current_db_user.id, reason=payload.reason)
    except service.HousekeepingError as exc:
        raise _refused(exc) from None
    out = await _out(db, task)
    await record_idempotent_response(db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id)
    return out
