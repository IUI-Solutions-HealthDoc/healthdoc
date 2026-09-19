"""Longitudinal care programs, condition registries, and chronic disease surveillance router (HD-28)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.programs import service
from app.programs.schemas import (
    CareProgramOut,
    ProgramEnrolmentCreate,
    ProgramEnrolmentExitRequest,
    ProgramEnrolmentOut,
    ProgramTimelineOut,
    ProgramVisitCreate,
    ProgramVisitOut,
)

router = APIRouter(prefix="/programs", tags=["programs"])

_PROGRAM_ROLES = ("doctor", "nurse", "supervisor", "admin")


@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "programs", "status": "ok"}


@router.get(
    "",
    response_model=list[CareProgramOut],
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def list_care_programs(
    db: AsyncSession = Depends(get_db),
) -> list[CareProgramOut]:
    """List available standardized chronic and longitudinal care programs."""
    return await service.list_care_programs(db)


@router.post(
    "/enrolments",
    response_model=ProgramEnrolmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def enrol_patient(
    body: ProgramEnrolmentCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ProgramEnrolmentOut:
    """Enrol patient into a condition registry / longitudinal care program."""
    enrolment = await service.enrol_patient(
        db=db,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return enrolment


@router.get(
    "/enrolments",
    response_model=list[ProgramEnrolmentOut],
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def list_enrolments(
    current_db_user: CurrentDbUser,
    program_code: str | None = Query(None, description="DIABETES_T2 | HYPERTENSION | ANC_MATERNAL | CKD_RENAL"),
    patient_id: uuid.UUID | None = None,
    status: str | None = Query(None, description="active | exited | completed"),
    db: AsyncSession = Depends(get_db),
) -> list[ProgramEnrolmentOut]:
    """List program enrolments for the facility."""
    return await service.list_enrolments(
        db=db,
        facility_id=current_db_user.facility_id,
        program_code=program_code,
        patient_id=patient_id,
        case_status=status,
    )


@router.get(
    "/enrolments/{enrolment_id}",
    response_model=ProgramTimelineOut,
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def get_enrolment_timeline(
    enrolment_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ProgramTimelineOut:
    """Get enrolment trajectory, goals, and complete visit metric timeline."""
    return await service.get_enrolment_timeline(
        db=db,
        enrolment_id=enrolment_id,
        facility_id=current_db_user.facility_id,
    )


@router.post(
    "/enrolments/{enrolment_id}/exit",
    response_model=ProgramEnrolmentOut,
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def exit_enrolment(
    enrolment_id: uuid.UUID,
    body: ProgramEnrolmentExitRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ProgramEnrolmentOut:
    """Exit or discharge a patient from a longitudinal care program."""
    enrolment = await service.exit_enrolment(
        db=db,
        enrolment_id=enrolment_id,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return enrolment


@router.post(
    "/enrolments/{enrolment_id}/visits",
    response_model=ProgramVisitOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_PROGRAM_ROLES))],
)
async def record_program_visit(
    enrolment_id: uuid.UUID,
    body: ProgramVisitCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ProgramVisitOut:
    """Record a longitudinal follow-up visit with clinical indicators and metrics."""
    visit = await service.record_program_visit(
        db=db,
        enrolment_id=enrolment_id,
        facility_id=current_db_user.facility_id,
        body=body,
        actor_user_id=current_db_user.id,
    )
    await db.commit()
    return visit
