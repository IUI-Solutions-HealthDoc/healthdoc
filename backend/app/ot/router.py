"""Operation Theatre (OT) router — scheduling, WHO checklist verification, and operative notes (HD-27)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.ot import service
from app.ot.schemas import (
    OtRecordCreate,
    OtScheduleCancelRequest,
    OtScheduleCreate,
    OtScheduleDetailOut,
    OtScheduleOut,
    WhoSafetyChecklistUpdate,
)

router = APIRouter(prefix="/ot", tags=["ot"])

_OT_ROLES = ("doctor", "nurse", "admin", "supervisor")


@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "ot", "status": "ok"}


@router.post(
    "/schedules",
    response_model=OtScheduleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def create_schedule(
    body: OtScheduleCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleOut:
    """Schedule a surgical case in an operating theatre room."""
    schedule = await service.create_ot_schedule(
        db=db,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return schedule


@router.get(
    "/schedules",
    response_model=list[OtScheduleOut],
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def list_schedules(
    current_db_user: CurrentDbUser,
    theatre_number: str | None = Query(None, description="Filter by theatre e.g. OT-1"),
    status: str | None = Query(None, description="scheduled | in_progress | completed | cancelled"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[OtScheduleOut]:
    """List operating theatre schedules for the caller's facility."""
    return await service.list_ot_schedules(
        db=db,
        facility_id=current_db_user.facility_id,
        theatre_number=theatre_number,
        case_status=status,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/schedules/{schedule_id}",
    response_model=OtScheduleDetailOut,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def get_schedule(
    schedule_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleDetailOut:
    """Get schedule details and operative notes."""
    return await service.get_ot_schedule(
        db=db,
        schedule_id=schedule_id,
        facility_id=current_db_user.facility_id,
    )


@router.patch(
    "/schedules/{schedule_id}/checklist",
    response_model=OtScheduleOut,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def update_safety_checklist(
    schedule_id: uuid.UUID,
    body: WhoSafetyChecklistUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleOut:
    """Sign off on WHO Surgical Safety Checklist (Sign-in, Time-out, Sign-out)."""
    schedule = await service.update_who_checklist(
        db=db,
        schedule_id=schedule_id,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return schedule


@router.post(
    "/schedules/{schedule_id}/start",
    response_model=OtScheduleOut,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def start_case(
    schedule_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleOut:
    """Transition scheduled surgery to in_progress."""
    schedule = await service.start_ot_case(
        db=db,
        schedule_id=schedule_id,
        facility_id=current_db_user.facility_id,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return schedule


@router.post(
    "/schedules/{schedule_id}/complete",
    response_model=OtScheduleDetailOut,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def complete_case(
    schedule_id: uuid.UUID,
    body: OtRecordCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleDetailOut:
    """Complete surgical case and record operative notes and swab/sponge reconciliation."""
    schedule = await service.complete_ot_case(
        db=db,
        schedule_id=schedule_id,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return schedule


@router.post(
    "/schedules/{schedule_id}/cancel",
    response_model=OtScheduleOut,
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def cancel_case(
    schedule_id: uuid.UUID,
    body: OtScheduleCancelRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OtScheduleOut:
    """Cancel an OT case with mandatory clinical/administrative reason."""
    schedule = await service.cancel_ot_case(
        db=db,
        schedule_id=schedule_id,
        facility_id=current_db_user.facility_id,
        cancel_reason=body.cancel_reason,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return schedule


@router.get(
    "/day-list",
    response_model=dict[str, list[OtScheduleOut]],
    dependencies=[Depends(require_roles(*_OT_ROLES))],
)
async def get_day_list(
    current_db_user: CurrentDbUser,
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[OtScheduleOut]]:
    """Get all surgical cases for the day grouped by operating theatre room."""
    day = target_date or date.today()
    return await service.get_theatre_day_list(
        db=db,
        facility_id=current_db_user.facility_id,
        target_date=day,
    )