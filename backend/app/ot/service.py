"""Operation Theatre service — schedule management, conflict prevention, WHO surgical safety checklist, and operative records (HD-27)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ot.models import OtRecord, OtSchedule
from app.ot.schemas import (
    OtRecordCreate,
    OtRecordOut,
    OtScheduleCreate,
    OtScheduleDetailOut,
    OtScheduleOut,
    WhoSafetyChecklistUpdate,
)
from app.patients.models import Patient
from app.admissions.models import Admission
from app.common.patient_scope import require_patient_scope, require_visit_scope


async def create_ot_schedule(
    db: AsyncSession,
    facility_id: uuid.UUID,
    body: OtScheduleCreate,
    actor_user_id: uuid.UUID,
) -> OtScheduleOut:
    """Create an OT schedule after enforcing ownership and theatre overlap."""
    await require_patient_scope(db, body.patient_id, facility_id)
    await require_visit_scope(db, body.visit_id, body.patient_id, facility_id)
    if body.admission_id:
        admission = (await db.execute(select(Admission.id).where(
            Admission.id == body.admission_id, Admission.visit_id == body.visit_id,
        ))).scalar_one_or_none()
        if admission is None:
            raise HTTPException(404, "Admission not found for this visit")
    if body.scheduled_end <= body.scheduled_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scheduled_end must be strictly greater than scheduled_start.",
        )

    # Concurrency and conflict guard: reject overlapping active cases in the same theatre
    conflict = (
        await db.execute(
            select(OtSchedule).where(
                OtSchedule.facility_id == facility_id,
                OtSchedule.theatre_number == body.theatre_number,
                OtSchedule.status.in_(["scheduled", "in_progress"]),
                OtSchedule.scheduled_start < body.scheduled_end,
                OtSchedule.scheduled_end > body.scheduled_start,
            )
        )
    ).scalar_one_or_none()

    if conflict is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Theatre '{body.theatre_number}' has a conflicting schedule "
                f"from {conflict.scheduled_start.isoformat()} to {conflict.scheduled_end.isoformat()} "
                f"(schedule ID: {conflict.id})."
            ),
        )

    schedule = OtSchedule(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=body.patient_id,
        visit_id=body.visit_id,
        theatre_number=body.theatre_number,
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
        procedure_name=body.procedure_name,
        status="scheduled",
        admission_id=body.admission_id,
        pre_op_checklist=body.pre_op_checklist,
        surgical_safety_confirmed=False,
        created_by=actor_user_id,
    )
    db.add(schedule)
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == body.patient_id))
    ).scalar_one_or_none()

    return OtScheduleOut(
        id=schedule.id,
        facility_id=schedule.facility_id,
        patient_id=schedule.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        visit_id=schedule.visit_id,
        theatre_number=schedule.theatre_number,
        scheduled_start=schedule.scheduled_start,
        scheduled_end=schedule.scheduled_end,
        procedure_name=schedule.procedure_name,
        status=schedule.status,
        admission_id=schedule.admission_id,
        pre_op_checklist=schedule.pre_op_checklist,
        cancel_reason=schedule.cancel_reason,
        surgical_safety_confirmed=schedule.surgical_safety_confirmed,
        created_at=schedule.created_at,
    )


async def list_ot_schedules(
    db: AsyncSession,
    facility_id: uuid.UUID,
    theatre_number: str | None = None,
    case_status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[OtScheduleOut]:
    """List OT schedules for a facility with patient metadata."""
    query = (
        select(OtSchedule, Patient.full_name, Patient.uhid)
        .join(Patient, Patient.id == OtSchedule.patient_id)
        .where(OtSchedule.facility_id == facility_id)
    )

    if theatre_number:
        query = query.where(OtSchedule.theatre_number == theatre_number)
    if case_status:
        query = query.where(OtSchedule.status == case_status)
    if date_from:
        query = query.where(OtSchedule.scheduled_start >= date_from)
    if date_to:
        query = query.where(OtSchedule.scheduled_end <= date_to)

    query = query.order_by(OtSchedule.scheduled_start.asc())
    rows = (await db.execute(query)).all()

    return [
        OtScheduleOut(
            id=sch.id,
            facility_id=sch.facility_id,
            patient_id=sch.patient_id,
            patient_name=full_name,
            patient_uhid=uhid,
            visit_id=sch.visit_id,
            theatre_number=sch.theatre_number,
            scheduled_start=sch.scheduled_start,
            scheduled_end=sch.scheduled_end,
            procedure_name=sch.procedure_name,
            status=sch.status,
            admission_id=sch.admission_id,
            pre_op_checklist=sch.pre_op_checklist,
            cancel_reason=sch.cancel_reason,
            surgical_safety_confirmed=sch.surgical_safety_confirmed,
            created_at=sch.created_at,
        )
        for sch, full_name, uhid in rows
    ]


async def get_ot_schedule(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    facility_id: uuid.UUID,
) -> OtScheduleDetailOut:
    """Get single OT schedule and its operative record."""
    row = (
        await db.execute(
            select(OtSchedule, Patient.full_name, Patient.uhid)
            .join(Patient, Patient.id == OtSchedule.patient_id)
            .where(OtSchedule.id == schedule_id, OtSchedule.facility_id == facility_id)
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OT Schedule {schedule_id} not found in this facility.",
        )

    sch, full_name, uhid = row
    record = (
        await db.execute(select(OtRecord).where(OtRecord.ot_schedule_id == schedule_id))
    ).scalar_one_or_none()

    return OtScheduleDetailOut(
        id=sch.id,
        facility_id=sch.facility_id,
        patient_id=sch.patient_id,
        patient_name=full_name,
        patient_uhid=uhid,
        visit_id=sch.visit_id,
        theatre_number=sch.theatre_number,
        scheduled_start=sch.scheduled_start,
        scheduled_end=sch.scheduled_end,
        procedure_name=sch.procedure_name,
        status=sch.status,
        admission_id=sch.admission_id,
        pre_op_checklist=sch.pre_op_checklist,
        cancel_reason=sch.cancel_reason,
        surgical_safety_confirmed=sch.surgical_safety_confirmed,
        created_at=sch.created_at,
        record=OtRecordOut.model_validate(record) if record else None,
    )


async def update_who_checklist(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    facility_id: uuid.UUID,
    body: WhoSafetyChecklistUpdate,
    actor_user_id: uuid.UUID,
) -> OtScheduleOut:
    """Sign off on WHO Surgical Safety Checklist phases (Sign-in, Time-out, Sign-out)."""
    schedule = (
        await db.execute(
            select(OtSchedule).where(
                OtSchedule.id == schedule_id, OtSchedule.facility_id == facility_id
            )
        )
    ).scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OT Schedule {schedule_id} not found.",
        )

    checklist_state = {
        "sign_in": body.sign_in_confirmed,
        "time_out": body.time_out_confirmed,
        "sign_out": body.sign_out_confirmed,
        "confirmed_by_role": body.confirmed_by_role,
        "notes": body.notes,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "verified_by_user_id": str(actor_user_id),
    }

    # WHO surgical safety checklist is confirmed when all three phases are complete
    all_phases_confirmed = (
        body.sign_in_confirmed and body.time_out_confirmed and body.sign_out_confirmed
    )

    schedule.pre_op_checklist = checklist_state
    schedule.surgical_safety_confirmed = all_phases_confirmed
    schedule.updated_by = actor_user_id
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == schedule.patient_id))
    ).scalar_one_or_none()

    return OtScheduleOut(
        id=schedule.id,
        facility_id=schedule.facility_id,
        patient_id=schedule.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        visit_id=schedule.visit_id,
        theatre_number=schedule.theatre_number,
        scheduled_start=schedule.scheduled_start,
        scheduled_end=schedule.scheduled_end,
        procedure_name=schedule.procedure_name,
        status=schedule.status,
        admission_id=schedule.admission_id,
        pre_op_checklist=schedule.pre_op_checklist,
        cancel_reason=schedule.cancel_reason,
        surgical_safety_confirmed=schedule.surgical_safety_confirmed,
        created_at=schedule.created_at,
    )


async def start_ot_case(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> OtScheduleOut:
    """Transition scheduled case into in_progress."""
    schedule = (
        await db.execute(
            select(OtSchedule).where(
                OtSchedule.id == schedule_id, OtSchedule.facility_id == facility_id
            )
        )
    ).scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OT Schedule {schedule_id} not found.",
        )

    if schedule.status != "scheduled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot start case with status '{schedule.status}'.",
        )

    schedule.status = "in_progress"
    schedule.updated_by = actor_user_id
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == schedule.patient_id))
    ).scalar_one_or_none()

    return OtScheduleOut(
        id=schedule.id,
        facility_id=schedule.facility_id,
        patient_id=schedule.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        visit_id=schedule.visit_id,
        theatre_number=schedule.theatre_number,
        scheduled_start=schedule.scheduled_start,
        scheduled_end=schedule.scheduled_end,
        procedure_name=schedule.procedure_name,
        status=schedule.status,
        admission_id=schedule.admission_id,
        pre_op_checklist=schedule.pre_op_checklist,
        cancel_reason=schedule.cancel_reason,
        surgical_safety_confirmed=schedule.surgical_safety_confirmed,
        created_at=schedule.created_at,
    )


async def complete_ot_case(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    facility_id: uuid.UUID,
    body: OtRecordCreate,
    actor_user_id: uuid.UUID,
) -> OtScheduleDetailOut:
    """Complete case and record operative notes, swab/sponge counts, and team sign-offs."""
    schedule = (
        await db.execute(
            select(OtSchedule).where(
                OtSchedule.id == schedule_id, OtSchedule.facility_id == facility_id
            )
        )
    ).scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OT Schedule {schedule_id} not found.",
        )

    if schedule.status not in ("scheduled", "in_progress"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot complete case with status '{schedule.status}'.",
        )

    # Sponge / needle count safety check
    if body.sponge_needle_count_correct is False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Surgical safety alert: Case completion blocked due to incorrect sponge/needle count.",
        )

    schedule.status = "completed"
    schedule.updated_by = actor_user_id

    # Create operative record
    record = OtRecord(
        id=uuid.uuid4(),
        ot_schedule_id=schedule_id,
        started_at=body.started_at,
        ended_at=body.ended_at or datetime.now(timezone.utc),
        surgeon_user_id=body.surgeon_user_id,
        anesthetist_user_id=body.anesthetist_user_id,
        notes=body.notes,
        pre_op_diagnosis=body.pre_op_diagnosis,
        post_op_diagnosis=body.post_op_diagnosis,
        procedure_performed=body.procedure_performed or schedule.procedure_name,
        anesthesia_type=body.anesthesia_type,
        scrub_nurse=body.scrub_nurse,
        circulating_nurse=body.circulating_nurse,
        implants_used=body.implants_used,
        sponge_needle_count_correct=body.sponge_needle_count_correct,
        specimens_sent=body.specimens_sent,
        complications=body.complications,
        recovery_status=body.recovery_status or "stable_in_pacu",
    )
    db.add(record)
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == schedule.patient_id))
    ).scalar_one_or_none()

    return OtScheduleDetailOut(
        id=schedule.id,
        facility_id=schedule.facility_id,
        patient_id=schedule.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        visit_id=schedule.visit_id,
        theatre_number=schedule.theatre_number,
        scheduled_start=schedule.scheduled_start,
        scheduled_end=schedule.scheduled_end,
        procedure_name=schedule.procedure_name,
        status=schedule.status,
        admission_id=schedule.admission_id,
        pre_op_checklist=schedule.pre_op_checklist,
        cancel_reason=schedule.cancel_reason,
        surgical_safety_confirmed=schedule.surgical_safety_confirmed,
        created_at=schedule.created_at,
        record=OtRecordOut.model_validate(record),
    )


async def cancel_ot_case(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    facility_id: uuid.UUID,
    cancel_reason: str,
    actor_user_id: uuid.UUID,
) -> OtScheduleOut:
    """Cancel an OT schedule with an explicit audit reason."""
    schedule = (
        await db.execute(
            select(OtSchedule).where(
                OtSchedule.id == schedule_id, OtSchedule.facility_id == facility_id
            )
        )
    ).scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OT Schedule {schedule_id} not found.",
        )

    if schedule.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot cancel an already completed OT case.",
        )

    schedule.status = "cancelled"
    schedule.cancel_reason = cancel_reason
    schedule.updated_by = actor_user_id
    await db.flush()

    patient = (
        await db.execute(select(Patient).where(Patient.id == schedule.patient_id))
    ).scalar_one_or_none()

    return OtScheduleOut(
        id=schedule.id,
        facility_id=schedule.facility_id,
        patient_id=schedule.patient_id,
        patient_name=patient.full_name if patient else None,
        patient_uhid=patient.uhid if patient else None,
        visit_id=schedule.visit_id,
        theatre_number=schedule.theatre_number,
        scheduled_start=schedule.scheduled_start,
        scheduled_end=schedule.scheduled_end,
        procedure_name=schedule.procedure_name,
        status=schedule.status,
        admission_id=schedule.admission_id,
        pre_op_checklist=schedule.pre_op_checklist,
        cancel_reason=schedule.cancel_reason,
        surgical_safety_confirmed=schedule.surgical_safety_confirmed,
        created_at=schedule.created_at,
    )


async def get_theatre_day_list(
    db: AsyncSession,
    facility_id: uuid.UUID,
    target_date: date,
) -> dict[str, list[OtScheduleOut]]:
    """Return day's cases grouped by theatre room."""
    start_dt = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)

    schedules = await list_ot_schedules(
        db=db,
        facility_id=facility_id,
        date_from=start_dt,
        date_to=end_dt,
    )

    grouped: dict[str, list[OtScheduleOut]] = {}
    for item in schedules:
        grouped.setdefault(item.theatre_number, []).append(item)

    return grouped
