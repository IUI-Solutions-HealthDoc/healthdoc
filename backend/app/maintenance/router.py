"""APIs for append-only equipment maintenance evidence."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import (
    check_idempotency,
    hash_request_body,
    record_idempotent_response,
)
from app.maintenance import service
from app.maintenance.schemas import (
    MaintenanceLogCreate,
    MaintenanceLogListOut,
    MaintenanceLogOut,
    MaintenanceType,
)

router = APIRouter(
    prefix="/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_roles("admin", "lab_tech", "radiology_tech"))],
)
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/logs", response_model=MaintenanceLogOut, status_code=201)
async def create_maintenance_log(
    payload: MaintenanceLogCreate,
    current_db_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> MaintenanceLogOut:
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    endpoint = "POST /maintenance/logs"
    request_hash = hash_request_body(payload)
    cached = await check_idempotency(
        db, idempotency_key, endpoint, request_hash, current_db_user.id
    )
    if cached is not None:
        return MaintenanceLogOut.model_validate(cached.response_body)

    try:
        row = await service.create_maintenance_log(
            db,
            payload=payload,
            facility_id=current_db_user.facility_id,
            actor_id=current_db_user.id,
        )
    except service.DepartmentNotFound:
        raise HTTPException(
            status_code=404, detail={"code": "department_not_found", "message": "Choose the department."},
        ) from None
    except service.MaintenanceRefused as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from None

    response = MaintenanceLogOut.model_validate(row)
    await record_idempotent_response(
        db,
        idempotency_key,
        endpoint,
        status.HTTP_201_CREATED,
        response.model_dump(mode="json"),
        current_db_user.id,
    )
    return response


@router.get("/logs", response_model=MaintenanceLogListOut)
async def list_maintenance_logs(
    current_db_user: CurrentDbUser,
    db: DbSession,
    machine_id: str | None = Query(default=None, min_length=1, max_length=50),
    department_id: uuid.UUID | None = None,
    maintenance_type: MaintenanceType | None = None,
    performed_from: datetime | None = None,
    performed_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MaintenanceLogListOut:
    if performed_from is not None and performed_to is not None:
        if performed_from > performed_to:
            raise HTTPException(status_code=422, detail="invalid_performed_range")
    rows, total = await service.list_maintenance_logs(
        db,
        facility_id=current_db_user.facility_id,
        machine_id=machine_id,
        department_id=department_id,
        maintenance_type=maintenance_type,
        performed_from=performed_from,
        performed_to=performed_to,
        page=page,
        page_size=page_size,
    )
    return MaintenanceLogListOut(
        items=[MaintenanceLogOut.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/logs/{log_id}", response_model=MaintenanceLogOut)
async def get_maintenance_log(
    log_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> MaintenanceLogOut:
    try:
        row = await service.get_maintenance_log(
            db, log_id=log_id, facility_id=current_db_user.facility_id
        )
    except service.MaintenanceLogNotFound:
        raise HTTPException(status_code=404, detail="maintenance_log_not_found") from None
    return MaintenanceLogOut.model_validate(row)
