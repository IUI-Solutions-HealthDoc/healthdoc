"""Equipment register: what machines a facility has and whether they work.

Admins register machines. Anyone who works with them (doctor, nurse, lab and
radiology technicians, HOD, admin) can report one down or back in service, with
a reason; every change is kept. The control room reads the counts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.equipment import service
from app.equipment.models import (
    EQUIPMENT_CATEGORIES,
    EQUIPMENT_STATUSES,
    Equipment,
    EquipmentStatusEvent,
)
from app.users.models import User

_VIEW = ("admin", "hod", "doctor", "nurse", "lab_tech", "radiology_tech", "supervisor")
_REPORT = ("admin", "hod", "doctor", "nurse", "lab_tech", "radiology_tech")

router = APIRouter(prefix="/equipment", tags=["equipment"], dependencies=[Depends(require_roles(*_VIEW))])

Category = Literal[EQUIPMENT_CATEGORIES]  # type: ignore[valid-type]
Status = Literal[EQUIPMENT_STATUSES]  # type: ignore[valid-type]


async def _idempotency_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key", "message": "Idempotency-Key header is required"})
    return idempotency_key


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: Category
    location: str | None = Field(default=None, max_length=120)
    asset_tag: str | None = Field(default=None, max_length=60)
    is_critical: bool = False


class StatusChange(BaseModel):
    status: Status
    reason: str | None = Field(default=None, max_length=500)


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    location: str | None
    asset_tag: str | None
    is_critical: bool
    status: str
    status_since: datetime
    status_reason: str | None


class StatusEventOut(BaseModel):
    from_status: str | None
    to_status: str
    reason: str | None
    changed_by: str
    changed_at: datetime


def _refused(exc: service.EquipmentError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


@router.get("", response_model=list[EquipmentOut])
async def list_equipment(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    status: Status | None = Query(None),
) -> list[EquipmentOut]:
    stmt = select(Equipment).where(Equipment.facility_id == current_db_user.facility_id)
    if status:
        stmt = stmt.where(Equipment.status == status)
    rows = (await db.execute(stmt.order_by(Equipment.status != "down", Equipment.name))).scalars().all()
    return [EquipmentOut.model_validate(row) for row in rows]


@router.post("", status_code=201, response_model=EquipmentOut, dependencies=[Depends(require_roles("admin"))])
async def register_equipment(
    payload: EquipmentCreate,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> EquipmentOut:
    endpoint, request_hash = "POST /equipment", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return EquipmentOut.model_validate(cached.response_body)
    try:
        equipment = await service.register(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id, **payload.model_dump()
        )
    except service.EquipmentError as exc:
        raise _refused(exc) from None
    out = EquipmentOut.model_validate(equipment)
    await record_idempotent_response(
        db, idempotency_key, endpoint, 201, out.model_dump(mode="json"), current_db_user.id
    )
    return out


@router.post("/{equipment_id}/status", response_model=EquipmentOut, dependencies=[Depends(require_roles(*_REPORT))])
async def change_equipment_status(
    equipment_id: uuid.UUID,
    payload: StatusChange,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> EquipmentOut:
    endpoint, request_hash = f"POST /equipment/{equipment_id}/status", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return EquipmentOut.model_validate(cached.response_body)
    if payload.status == "retired" and "admin" not in current_db_user.roles:
        raise HTTPException(403, {"code": "admin_only", "message": "Only an admin retires a machine"})
    try:
        equipment = await service.get_scoped(db, equipment_id, current_db_user.facility_id, lock=True)
        await service.change_status(
            db, equipment, to_status=payload.status, reason=payload.reason, user_id=current_db_user.id
        )
    except service.EquipmentError as exc:
        raise _refused(exc) from None
    out = EquipmentOut.model_validate(equipment)
    await record_idempotent_response(
        db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id
    )
    return out


@router.get("/{equipment_id}/history", response_model=list[StatusEventOut])
async def equipment_history(
    equipment_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> list[StatusEventOut]:
    try:
        await service.get_scoped(db, equipment_id, current_db_user.facility_id)
    except service.EquipmentError as exc:
        raise _refused(exc) from None
    rows = (
        await db.execute(
            select(EquipmentStatusEvent, User.full_name)
            .join(User, User.id == EquipmentStatusEvent.changed_by)
            .where(EquipmentStatusEvent.equipment_id == equipment_id)
            .order_by(EquipmentStatusEvent.changed_at.desc())
            .limit(100)
        )
    ).all()
    return [
        StatusEventOut(
            from_status=e.from_status, to_status=e.to_status, reason=e.reason, changed_by=name, changed_at=e.changed_at
        )
        for e, name in rows
    ]
