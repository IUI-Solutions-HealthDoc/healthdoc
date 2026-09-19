"""Emergency identity logic — THID generation and THID→UHID promotion (W5-01).

THID format: TH-FACILITY-YYMMDD-SEQ4
Example:     TH-JPR001-260714-0007  (docs/database-schema.md §3, 0006)

Mirrors patients/service.py's UHID sequence pattern (real Postgres SEQUENCE,
never MAX(col)+1, per schema-conventions.md §2.2) — but keyed per facility+day
instead of per facility+year, since emergency IDs are issued far more densely.

THID sequences are per facility+day — too numerous to pre-create at facility
insert (unlike UHID which is per facility+year). Created on first use of the
day via the 42P01 fallback in _next_thid_sequence().

W5-01 promote flow (schema doc §Account governance):
  supervisor A calls request_promotion()  → creates merge log (pending)
  supervisor B calls approve_promotion()  → generates UHID, updates patient
  supervisor C calls unmerge_promotion()  → reverses, different from B (maker-checker)
  superadmin is explicitly barred from all three (no clinical access, v3.8).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.audit.service import audited_mutation
from app.patients.models import Patient, PatientMergeLog
from app.patients.service import generate_uhid

_FACILITY_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


# ---------------------------------------------------------------------------
# THID generation
# ---------------------------------------------------------------------------

def _current_day_str(facility_timezone: str = "Asia/Kolkata") -> str:
    """Derives the current date string in the facility's local timezone.

    Using UTC risks issuing a THID with yesterday's date between 00:00
    and 05:30 IST — wrong forever, and lands on a different sequence too.
    Same rule as UHID's _current_year_for_facility().
    """
    import zoneinfo
    tz = zoneinfo.ZoneInfo(facility_timezone)
    return datetime.now(tz).strftime("%y%m%d")


def _thid_sequence_name(facility_code: str, day_str: str) -> str:
    if not _FACILITY_CODE_RE.match(facility_code):
        raise ValueError(f"facility_code contains invalid characters: {facility_code!r}")
    return f"seq_thid_{facility_code.lower()}_{day_str}"


async def _next_thid_sequence(db: AsyncSession, facility_code: str, day_str: str) -> int:
    """Run CREATE SEQUENCE IF NOT EXISTS unconditionally before nextval.

    The previous 42P01 catch-and-recover pattern cannot work — Postgres
    aborts the transaction on that error, so every statement after it
    returns 25P02. Running CREATE SEQUENCE IF NOT EXISTS first is
    idempotent and removes the error path entirely.
    """
    seq_name = _thid_sequence_name(facility_code, day_str)
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
    result = await db.execute(
        text("SELECT nextval(:seq_name)"), {"seq_name": seq_name}
    )
    return result.scalar()


async def generate_thid(
    db: AsyncSession, facility_code: str, facility_timezone: str = "Asia/Kolkata"
) -> str:
    day_str = _current_day_str(facility_timezone)
    next_seq = await _next_thid_sequence(db, facility_code, day_str)
    seq_str = str(next_seq).zfill(4)
    return f"TH-{facility_code}-{day_str}-{seq_str}"


# ---------------------------------------------------------------------------
# W5-01: THID → UHID promotion
# ---------------------------------------------------------------------------

def _patient_snapshot(patient: Patient) -> dict:
    """Minimal snapshot for merge log before/after."""
    return {
        "id": str(patient.id),
        "uhid": patient.uhid,
        "thid": patient.thid,
        "status": patient.status,
        "identity_path": patient.identity_path,
    }


async def request_promotion(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    reason: str | None,
    requested_by: uuid.UUID,
) -> PatientMergeLog:
    """Supervisor requests THID→UHID promotion for an emergency patient.

    Creates a pending merge log entry. A second, different supervisor must
    call approve_promotion() — same maker-checker rule as UHID merges.
    Does NOT generate the UHID yet — that happens only on approval.
    """
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ValueError("patient_not_found")
    if patient.facility_id != facility_id:
        raise ValueError("patient_not_found")  # don't leak cross-facility existence
    if patient.identity_path != "thid":
        raise ValueError("patient_not_thid")
    if patient.status != "active":
        raise ValueError(f"patient_not_active: status={patient.status}")

    existing = (
        await db.execute(
            select(PatientMergeLog).where(
                PatientMergeLog.source_patient_id == patient_id,
                PatientMergeLog.source_type == "thid",
                PatientMergeLog.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("promotion_already_pending")

    merge_log = PatientMergeLog(
        source_type="thid",
        source_patient_id=patient_id,
        target_patient_id=patient_id,  # self-promotion — same patient gets a UHID
        requested_by=requested_by,
        status="pending",
        reason=reason,
        before_snapshot=_patient_snapshot(patient),
    )
    db.add(merge_log)
    await db.flush()
    await db.refresh(merge_log)
    return merge_log


async def approve_promotion(
    db: AsyncSession,
    *,
    merge_log_id: uuid.UUID,
    facility_id: uuid.UUID,
    approved_by: uuid.UUID,
    state_code: str,
    facility_code: str,
    facility_timezone: str = "Asia/Kolkata",
) -> PatientMergeLog:
    """Different supervisor approves — generates UHID, updates patient.

    Locked with SELECT FOR UPDATE to prevent two concurrent approvals.
    Self-approval blocked (maker-checker).
    """
    from datetime import timezone

    merge_log = (
        await db.execute(
            select(PatientMergeLog)
            .where(PatientMergeLog.id == merge_log_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if not merge_log:
        raise ValueError("merge_log_not_found")
    if merge_log.status != "pending":
        raise ValueError(f"not_pending: status={merge_log.status}")
    if merge_log.source_type != "thid":
        raise ValueError("not_a_thid_promotion")
    if merge_log.requested_by == approved_by:
        raise ValueError("self_approval_not_allowed")

    patient = await db.get(Patient, merge_log.source_patient_id)
    if patient is None:
        raise ValueError("patient_not_found")
    if patient.facility_id != facility_id:
        raise ValueError("patient_not_found")
    if patient.identity_path != "thid":
        raise ValueError("patient_already_promoted")
    if patient.uhid is not None:
        raise ValueError("patient_already_has_uhid")

    uhid = await generate_uhid(
        db,
        state_code=state_code,
        facility_code=facility_code,
        facility_timezone=facility_timezone,
    )

    async with audited_mutation(
        db,
        facility_id=patient.facility_id,
        action=AuditAction.THID_MERGE,
        resource_type="patients",
        patient_id=patient.id,
    ) as audit:
        audit.resource_id = patient.id
        audit.old_value = {"uhid": None, "identity_path": "thid"}
        patient.uhid = uhid
        patient.identity_path = "demographics_only"
        patient.updated_by = approved_by
        patient.row_version += 1
        audit.new_value = {"uhid": uhid, "identity_path": "demographics_only"}
        audit.reason = merge_log.reason

    merge_log.status = "approved"
    merge_log.approved_by = approved_by
    merge_log.approved_at = datetime.now(timezone.utc)
    merge_log.after_snapshot = _patient_snapshot(patient)

    await db.flush()
    await db.refresh(merge_log)
    return merge_log


async def unmerge_promotion(
    db: AsyncSession,
    *,
    merge_log_id: uuid.UUID,
    facility_id: uuid.UUID,
    unmerged_by: uuid.UUID,
    unmerge_reason: str | None,
) -> PatientMergeLog:
    """Supervisor (different from approver) reverses an approved THID promotion.

    Schema doc v3.8: unmerge is supervisor only, never superadmin.
    The approving supervisor must be a different person (maker-checker).
    Restores patient to THID state: clears uhid, resets identity_path to 'thid'.
    """
    merge_log = (
        await db.execute(
            select(PatientMergeLog)
            .where(PatientMergeLog.id == merge_log_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if not merge_log:
        raise ValueError("merge_log_not_found")
    if merge_log.status != "approved":
        raise ValueError(f"not_approved: status={merge_log.status}")
    if merge_log.source_type != "thid":
        raise ValueError("not_a_thid_promotion")
    if merge_log.approved_by == unmerged_by:
        raise ValueError("self_unmerge_not_allowed")

    patient = await db.get(Patient, merge_log.source_patient_id)
    if patient is None:
        raise ValueError("patient_not_found")
    if patient.facility_id != facility_id:
        raise ValueError("patient_not_found")

    async with audited_mutation(
        db,
        facility_id=patient.facility_id,
        action=AuditAction.THID_UNMERGE,
        resource_type="patients",
        patient_id=patient.id,
    ) as audit:
        audit.resource_id = patient.id
        audit.old_value = {"uhid": patient.uhid, "identity_path": patient.identity_path}
        patient.uhid = None
        patient.identity_path = "thid"
        patient.updated_by = unmerged_by
        patient.row_version += 1
        audit.new_value = {"uhid": None, "identity_path": "thid"}
        audit.reason = unmerge_reason

    merge_log.status = "unmerged"
    merge_log.unmerge_reason = unmerge_reason

    await db.flush()
    await db.refresh(merge_log)
    return merge_log


async def get_emergency_worklist(
    db: AsyncSession, facility_id: uuid.UUID
) -> list[dict]:
    """List active emergency arrivals for the facility.

    Joins active emergency visits with patient records so clinicians
    can open consultations without requiring an OPD queue token.
    """
    from app.opd.models import Visit

    stmt = (
        select(Visit, Patient)
        .join(Patient, Patient.id == Visit.patient_id)
        .where(
            Visit.facility_id == facility_id,
            Visit.visit_type == "emergency",
            Visit.status.in_(["created", "active", "in_progress", "admitted"]),
        )
        .order_by(Visit.created_at.desc())
    )
    result = await db.execute(stmt)
    items = []
    for visit, patient in result.all():
        items.append({
            "visit_id": visit.id,
            "visit_number": visit.visit_number,
            "patient_id": patient.id,
            "thid": patient.thid,
            "uhid": patient.uhid,
            "full_name": patient.full_name,
            "age_years": patient.age_years,
            "sex": patient.sex,
            "arrival_time": visit.created_at,
            "status": visit.status,
            "visit_type": visit.visit_type,
        })
    return items


# ---------------------------------------------------------------------------
# HD-18: ED Triage Service Implementations
# ---------------------------------------------------------------------------

async def create_triage(
    db: AsyncSession,
    payload: EmergencyTriageCreate,
    *,
    facility_id: uuid.UUID,
    triaged_by: uuid.UUID,
) -> EmergencyTriage:
    """Records an initial emergency triage assessment."""
    from app.emergency.models import EmergencyTriage

    triage = EmergencyTriage(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=payload.patient_id,
        visit_id=payload.visit_id,
        acuity_level=payload.acuity_level,
        chief_complaint=payload.chief_complaint,
        triage_notes=payload.triage_notes,
        assigned_doctor_id=payload.assigned_doctor_id,
        assigned_bay=payload.assigned_bay,
        status="waiting",
        triaged_at=payload.triaged_at or datetime.now(timezone.utc),
        triaged_by=triaged_by,
        created_by=triaged_by,
        updated_by=triaged_by,
    )
    db.add(triage)
    await db.flush()
    await db.refresh(triage)
    return triage


async def re_triage(
    db: AsyncSession,
    triage_id: uuid.UUID,
    payload: EmergencyReTriageRequest,
    *,
    changed_by: uuid.UUID,
) -> EmergencyTriage:
    """Updates acuity level with a mandatory clinical reasoning log entry."""
    from app.emergency.models import EmergencyTriage, EmergencyTriageLog

    triage = await db.get(EmergencyTriage, triage_id)
    if triage is None:
        raise ValueError("Emergency triage not found")

    if triage.acuity_level == payload.new_acuity:
        raise ValueError("New acuity must be different from current acuity")

    log_entry = EmergencyTriageLog(
        id=uuid.uuid4(),
        triage_id=triage.id,
        previous_acuity=triage.acuity_level,
        new_acuity=payload.new_acuity,
        reason=payload.reason,
        changed_by=changed_by,
        changed_at=datetime.now(timezone.utc),
    )
    db.add(log_entry)

    triage.acuity_level = payload.new_acuity
    triage.updated_by = changed_by
    triage.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(triage)
    return triage


async def update_triage(
    db: AsyncSession,
    triage_id: uuid.UUID,
    payload: EmergencyTriageUpdate,
    *,
    updated_by: uuid.UUID,
) -> EmergencyTriage:
    """Updates triage status, bed/bay, clinician, or disposition."""
    from app.emergency.models import EmergencyTriage

    triage = await db.get(EmergencyTriage, triage_id)
    if triage is None:
        raise ValueError("Emergency triage not found")

    now = datetime.now(timezone.utc)
    if payload.status is not None:
        triage.status = payload.status
        if payload.status == "in_treatment" and triage.clinician_seen_at is None:
            triage.clinician_seen_at = now

    if payload.clinician_seen and triage.clinician_seen_at is None:
        triage.clinician_seen_at = now
        if triage.status == "waiting":
            triage.status = "in_treatment"

    if payload.assigned_doctor_id is not None:
        triage.assigned_doctor_id = payload.assigned_doctor_id
    if payload.assigned_bay is not None:
        triage.assigned_bay = payload.assigned_bay

    if payload.disposition is not None:
        triage.disposition = payload.disposition
        triage.disposition_at = now
        if payload.disposition_notes is not None:
            triage.disposition_notes = payload.disposition_notes
        if payload.disposition in ("discharge", "admit", "lwbs"):
            triage.status = "discharged" if payload.disposition == "discharge" else (
                "admitted" if payload.disposition == "admit" else "lwbs"
            )

    triage.updated_by = updated_by
    triage.updated_at = now

    await db.flush()
    await db.refresh(triage)
    return triage


async def list_active_triages(
    db: AsyncSession,
    facility_id: uuid.UUID,
    *,
    status_filter: str | None = None,
) -> list[dict]:
    """Returns active emergency tracking board rows with clinical metrics and logs."""
    from app.emergency.models import EmergencyTriage, EmergencyTriageLog
    from app.users.models import User
    from sqlalchemy import case

    acuity_order = case(
        (EmergencyTriage.acuity_level == "resuscitation", 1),
        (EmergencyTriage.acuity_level == "emergent", 2),
        (EmergencyTriage.acuity_level == "urgent", 3),
        else_=4,
    )

    query = (
        select(EmergencyTriage, Patient, User)
        .join(Patient, Patient.id == EmergencyTriage.patient_id)
        .outerjoin(User, User.id == EmergencyTriage.assigned_doctor_id)
        .where(EmergencyTriage.facility_id == facility_id)
    )

    if status_filter:
        query = query.where(EmergencyTriage.status == status_filter)
    else:
        query = query.where(EmergencyTriage.status.in_(["waiting", "in_treatment"]))

    query = query.order_by(acuity_order, EmergencyTriage.triaged_at.asc())
    results = (await db.execute(query)).all()

    now = datetime.now(timezone.utc)
    items = []
    for triage, patient, doctor in results:
        # Fetch logs for this triage
        logs_stmt = (
            select(EmergencyTriageLog)
            .where(EmergencyTriageLog.triage_id == triage.id)
            .order_by(EmergencyTriageLog.changed_at.desc())
        )
        logs_result = (await db.execute(logs_stmt)).scalars().all()

        triaged_at = triage.triaged_at if triage.triaged_at.tzinfo else triage.triaged_at.replace(tzinfo=timezone.utc)
        clinician_seen_at = (
            triage.clinician_seen_at if (triage.clinician_seen_at is None or triage.clinician_seen_at.tzinfo)
            else triage.clinician_seen_at.replace(tzinfo=timezone.utc)
        )

        minutes_seen = None
        if clinician_seen_at:
            minutes_seen = int((clinician_seen_at - triaged_at).total_seconds() / 60)
        else:
            minutes_seen = int((now - triaged_at).total_seconds() / 60)

        items.append({
            "id": triage.id,
            "facility_id": triage.facility_id,
            "patient_id": triage.patient_id,
            "visit_id": triage.visit_id,
            "acuity_level": triage.acuity_level,
            "chief_complaint": triage.chief_complaint,
            "triage_notes": triage.triage_notes,
            "assigned_doctor_id": triage.assigned_doctor_id,
            "assigned_bay": triage.assigned_bay,
            "status": triage.status,
            "triaged_at": triage.triaged_at,
            "triaged_by": triage.triaged_by,
            "clinician_seen_at": triage.clinician_seen_at,
            "door_to_clinician_minutes": minutes_seen,
            "disposition": triage.disposition,
            "disposition_at": triage.disposition_at,
            "disposition_notes": triage.disposition_notes,
            "created_at": triage.created_at,
            "patient_name": patient.full_name,
            "patient_identifier": patient.thid or patient.uhid or str(patient.id)[:8],
            "doctor_name": doctor.full_name if doctor else None,
            "logs": logs_result,
        })
    return items


async def get_emergency_metrics(
    db: AsyncSession,
    facility_id: uuid.UUID,
) -> dict:
    """Calculates ED key performance metrics and census breakdown."""
    from app.emergency.models import EmergencyTriage

    stmt = select(EmergencyTriage).where(EmergencyTriage.facility_id == facility_id)
    all_triages = (await db.execute(stmt)).scalars().all()

    active = [t for t in all_triages if t.status in ("waiting", "in_treatment")]
    waiting = [t for t in active if t.status == "waiting"]
    in_tx = [t for t in active if t.status == "in_treatment"]
    lwbs = [t for t in all_triages if t.status == "lwbs" or t.disposition == "lwbs"]

    resuscitation = [t for t in active if t.acuity_level == "resuscitation"]
    emergent = [t for t in active if t.acuity_level == "emergent"]
    urgent = [t for t in active if t.acuity_level == "urgent"]
    non_urgent = [t for t in active if t.acuity_level == "non_urgent"]

    door_times = []
    for t in all_triages:
        if t.clinician_seen_at is not None:
            t_triaged = t.triaged_at if t.triaged_at.tzinfo else t.triaged_at.replace(tzinfo=timezone.utc)
            t_seen = t.clinician_seen_at if t.clinician_seen_at.tzinfo else t.clinician_seen_at.replace(tzinfo=timezone.utc)
            if t_seen >= t_triaged:
                door_times.append((t_seen - t_triaged).total_seconds() / 60)
    avg_door = (sum(door_times) / len(door_times)) if door_times else None

    return {
        "active_census": len(active),
        "waiting_count": len(waiting),
        "in_treatment_count": len(in_tx),
        "resuscitation_count": len(resuscitation),
        "emergent_count": len(emergent),
        "urgent_count": len(urgent),
        "non_urgent_count": len(non_urgent),
        "avg_door_to_clinician_minutes": round(avg_door, 1) if avg_door is not None else None,
        "lwbs_count": len(lwbs),
    }


