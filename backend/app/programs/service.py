"""Longitudinal care programs service — registry, single-active enrolment rule, and metric tracking encounters (HD-28)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.patients.models import Patient
from app.common.patient_scope import require_patient_scope
from app.programs.models import CareProgram, ProgramEnrolment, ProgramVisit
from app.programs.schemas import (
    CareProgramOut,
    ProgramEnrolmentCreate,
    ProgramEnrolmentExitRequest,
    ProgramEnrolmentOut,
    ProgramTimelineOut,
    ProgramVisitCreate,
    ProgramVisitOut,
)

# Standard default programs if DB seed has not executed
DEFAULT_PROGRAMS = [
    {
        "program_code": "DIABETES_T2",
        "program_name": "Type 2 Diabetes Mellitus Care Program",
        "category": "chronic",
        "description": "Comprehensive glycaemic monitoring, HbA1c tracking, renal and retinopathy surveillance.",
    },
    {
        "program_code": "HYPERTENSION",
        "program_name": "Essential Hypertension Care Program",
        "category": "chronic",
        "description": "Cardiovascular risk stratification, BP tracking, and end-organ protection surveillance.",
    },
    {
        "program_code": "ANC_MATERNAL",
        "program_name": "Antenatal & Maternal Longitudinal Care",
        "category": "maternal",
        "description": "Trimester tracking, fetal growth surveillance, high-risk screening, and immunization scheduling.",
    },
    {
        "program_code": "CKD_RENAL",
        "program_name": "Chronic Kidney Disease Care Program",
        "category": "chronic",
        "description": "eGFR progression monitoring, proteinuria tracking, and mineral metabolism surveillance.",
    },
]


async def list_care_programs(db: AsyncSession) -> list[CareProgramOut]:
    """List available standardized longitudinal care programs."""
    programs = (
        await db.execute(
            select(CareProgram).where(CareProgram.is_active == True).order_by(CareProgram.program_code)
        )
    ).scalars().all()

    if not programs:
        # Fallback to defaults if migration seed hasn't run in the current session
        for p in DEFAULT_PROGRAMS:
            cp = CareProgram(
                id=uuid.uuid4(),
                program_code=p["program_code"],
                program_name=p["program_name"],
                category=p["category"],
                description=p["description"],
                is_active=True,
            )
            db.add(cp)
        await db.flush()
        programs = (
            await db.execute(
                select(CareProgram).where(CareProgram.is_active == True).order_by(CareProgram.program_code)
            )
        ).scalars().all()

    return [CareProgramOut.model_validate(p) for p in programs]


async def enrol_patient(
    db: AsyncSession,
    facility_id: uuid.UUID,
    body: ProgramEnrolmentCreate,
    actor_user_id: uuid.UUID,
) -> ProgramEnrolmentOut:
    """Enrol patient into a care program, enforcing single-active-enrolment rule."""
    await require_patient_scope(db, body.patient_id, facility_id)
    patient = (
        await db.execute(select(Patient).where(Patient.id == body.patient_id))
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {body.patient_id} not found.",
        )

    # Invariant: Prevent duplicate active enrolments for the same patient & program
    active_enrolment = (
        await db.execute(
            select(ProgramEnrolment).where(
                ProgramEnrolment.patient_id == body.patient_id,
                ProgramEnrolment.program_code == body.program_code,
                ProgramEnrolment.status == "active",
            )
        )
    ).scalar_one_or_none()

    if active_enrolment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Patient {patient.full_name} is already actively enrolled in program "
                f"'{body.program_code}' (Enrolment ID: {active_enrolment.id})."
            ),
        )

    # Resolve program title
    prog = (
        await db.execute(
            select(CareProgram).where(CareProgram.program_code == body.program_code)
        )
    ).scalar_one_or_none()
    program_name = prog.program_name if prog else body.program_code

    enrolment_date = body.enrolment_date or date.today()

    enrolment = ProgramEnrolment(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=body.patient_id,
        program_code=body.program_code,
        program_name=program_name,
        enrolment_date=enrolment_date,
        status="active",
        target_outcomes=body.target_outcomes,
        enrolled_by=actor_user_id,
    )
    db.add(enrolment)
    await db.flush()

    interval = prog.review_interval_days if prog is not None else None
    if interval is not None and interval > 0:
        db.add(ProgramVisit(
            id=uuid.uuid4(),
            enrolment_id=enrolment.id,
            scheduled_date=enrolment_date + timedelta(days=interval),
            status="scheduled",
            clinical_summary="Scheduled program review.",
        ))
        await db.flush()

    return ProgramEnrolmentOut(
        id=enrolment.id,
        facility_id=enrolment.facility_id,
        patient_id=enrolment.patient_id,
        patient_name=patient.full_name,
        patient_uhid=patient.uhid,
        program_code=enrolment.program_code,
        program_name=enrolment.program_name,
        enrolment_date=enrolment.enrolment_date,
        status=enrolment.status,
        exit_date=enrolment.exit_date,
        exit_reason=enrolment.exit_reason,
        target_outcomes=enrolment.target_outcomes,
        enrolled_by=enrolment.enrolled_by,
        created_at=enrolment.created_at,
    )


async def list_enrolments(
    db: AsyncSession,
    facility_id: uuid.UUID,
    program_code: str | None = None,
    patient_id: uuid.UUID | None = None,
    case_status: str | None = None,
) -> list[ProgramEnrolmentOut]:
    """List care program enrolments for a facility."""
    query = (
        select(ProgramEnrolment, Patient.full_name, Patient.uhid)
        .join(Patient, Patient.id == ProgramEnrolment.patient_id)
        .where(ProgramEnrolment.facility_id == facility_id)
    )

    if program_code:
        query = query.where(ProgramEnrolment.program_code == program_code)
    if patient_id:
        query = query.where(ProgramEnrolment.patient_id == patient_id)
    if case_status:
        query = query.where(ProgramEnrolment.status == case_status)

    query = query.order_by(ProgramEnrolment.enrolment_date.desc())
    rows = (await db.execute(query)).all()

    return [
        ProgramEnrolmentOut(
            id=enr.id,
            facility_id=enr.facility_id,
            patient_id=enr.patient_id,
            patient_name=full_name,
            patient_uhid=uhid,
            program_code=enr.program_code,
            program_name=enr.program_name,
            enrolment_date=enr.enrolment_date,
            status=enr.status,
            exit_date=enr.exit_date,
            exit_reason=enr.exit_reason,
            target_outcomes=enr.target_outcomes,
            enrolled_by=enr.enrolled_by,
            created_at=enr.created_at,
        )
        for enr, full_name, uhid in rows
    ]


async def exit_enrolment(
    db: AsyncSession,
    enrolment_id: uuid.UUID,
    facility_id: uuid.UUID,
    body: ProgramEnrolmentExitRequest,
    actor_user_id: uuid.UUID,
) -> ProgramEnrolmentOut:
    """Exit or discharge a patient from an active longitudinal care program."""
    enrolment = (
        await db.execute(
            select(ProgramEnrolment).where(
                ProgramEnrolment.id == enrolment_id,
                ProgramEnrolment.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()

    if enrolment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program enrolment {enrolment_id} not found.",
        )

    if enrolment.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot exit enrolment with status '{enrolment.status}'.",
        )

    enrolment.status = "exited"
    enrolment.exit_date = body.exit_date
    enrolment.exit_reason = body.exit_reason
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == enrolment.patient_id))
    ).scalar_one_or_none()

    return ProgramEnrolmentOut(
        id=enrolment.id,
        facility_id=enrolment.facility_id,
        patient_id=enrolment.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        program_code=enrolment.program_code,
        program_name=enrolment.program_name,
        enrolment_date=enrolment.enrolment_date,
        status=enrolment.status,
        exit_date=enrolment.exit_date,
        exit_reason=enrolment.exit_reason,
        target_outcomes=enrolment.target_outcomes,
        enrolled_by=enrolment.enrolled_by,
        created_at=enrolment.created_at,
    )


async def record_program_visit(
    db: AsyncSession,
    enrolment_id: uuid.UUID,
    facility_id: uuid.UUID,
    body: ProgramVisitCreate,
    actor_user_id: uuid.UUID,
) -> ProgramVisitOut:
    """Record a longitudinal follow-up visit with updated clinical metrics."""
    enrolment = (
        await db.execute(
            select(ProgramEnrolment).where(
                ProgramEnrolment.id == enrolment_id,
                ProgramEnrolment.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()

    if enrolment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program enrolment {enrolment_id} not found.",
        )

    completed_date = body.completed_date or date.today()

    visit = ProgramVisit(
        id=uuid.uuid4(),
        enrolment_id=enrolment_id,
        scheduled_date=body.scheduled_date,
        completed_date=completed_date,
        status="completed",
        metrics=body.metrics,
        clinical_summary=body.clinical_summary,
        conducted_by=actor_user_id,
    )
    db.add(visit)
    await db.flush()

    return ProgramVisitOut(
        id=visit.id,
        enrolment_id=visit.enrolment_id,
        scheduled_date=visit.scheduled_date,
        completed_date=visit.completed_date,
        status=visit.status,
        metrics=visit.metrics,
        clinical_summary=visit.clinical_summary,
        conducted_by=visit.conducted_by,
        created_at=visit.created_at,
    )


async def get_enrolment_timeline(
    db: AsyncSession,
    enrolment_id: uuid.UUID,
    facility_id: uuid.UUID,
) -> ProgramTimelineOut:
    """Retrieve full longitudinal timeline and metric history for a patient's enrolment."""
    row = (
        await db.execute(
            select(ProgramEnrolment, Patient.full_name, Patient.uhid)
            .join(Patient, Patient.id == ProgramEnrolment.patient_id)
            .where(
                ProgramEnrolment.id == enrolment_id,
                ProgramEnrolment.facility_id == facility_id,
            )
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program enrolment {enrolment_id} not found.",
        )

    enr, full_name, uhid = row

    visits = (
        await db.execute(
            select(ProgramVisit)
            .where(ProgramVisit.enrolment_id == enrolment_id)
            .order_by(ProgramVisit.scheduled_date.asc())
        )
    ).scalars().all()

    enrolment_out = ProgramEnrolmentOut(
        id=enr.id,
        facility_id=enr.facility_id,
        patient_id=enr.patient_id,
        patient_name=full_name,
        patient_uhid=uhid,
        program_code=enr.program_code,
        program_name=enr.program_name,
        enrolment_date=enr.enrolment_date,
        status=enr.status,
        exit_date=enr.exit_date,
        exit_reason=enr.exit_reason,
        target_outcomes=enr.target_outcomes,
        enrolled_by=enr.enrolled_by,
        created_at=enr.created_at,
    )

    return ProgramTimelineOut(
        enrolment=enrolment_out,
        visits=[ProgramVisitOut.model_validate(v) for v in visits],
    )
