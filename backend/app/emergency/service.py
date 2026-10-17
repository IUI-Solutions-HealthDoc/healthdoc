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
from datetime import UTC, datetime, timedelta, timezone

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


EMERGENCY_STALE_HOURS = 24


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
            Visit.status.in_(["registered", "in_consultation"]),
        )
        .order_by(Visit.created_at.desc())
    )
    result = await db.execute(stmt)
    from app.emergency.models import EmergencyTriage

    # A patient whose triage is closed (admitted, discharged, left) has left
    # the ED even while the visit row stays open for the ward.
    closed = set(
        (
            await db.execute(
                select(EmergencyTriage.visit_id).where(
                    EmergencyTriage.facility_id == facility_id,
                    EmergencyTriage.status.notin_(ACTIVE_TRIAGE_STATUSES),
                )
            )
        ).scalars().all()
    )
    items = []
    # Visits from early September still sat in "awaiting care" in mid October
    # (QA 10 Oct 2026); the board flags them instead of mixing them in.
    stale_before = datetime.now(UTC) - timedelta(hours=EMERGENCY_STALE_HOURS)
    for visit, patient in result.all():
        if visit.id in closed:
            continue
        created = visit.created_at if visit.created_at.tzinfo else visit.created_at.replace(tzinfo=UTC)
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
            "stale": created < stale_before,
        })
    return items


# ---------------------------------------------------------------------------
# HD-18: ED Triage Service Implementations
# ---------------------------------------------------------------------------

class TriageRefused(ValueError):
    """A triage write the ED rules refuse. `code` and `message` reach the screen."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


ACTIVE_TRIAGE_STATUSES = ("waiting", "in_treatment")
HIGH_ACUITY = ("resuscitation", "emergent")
# Door-to-clinician is a shift measure; an all-time average barely moved and
# read as a fixed number on every registration (QA 16-17 Oct 2026).
DOOR_TO_CLINICIAN_WINDOW_HOURS = 24


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _triage_in_facility(db: AsyncSession, triage_id: uuid.UUID, facility_id: uuid.UUID):
    """404 for another facility's triage, never 403 (enumeration oracle)."""
    from app.emergency.models import EmergencyTriage

    triage = (
        await db.execute(
            select(EmergencyTriage)
            .where(EmergencyTriage.id == triage_id, EmergencyTriage.facility_id == facility_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if triage is None:
        raise TriageRefused("triage_not_found", "This triage record was not found.", 404)
    return triage


async def create_triage(
    db: AsyncSession,
    payload: EmergencyTriageCreate,
    *,
    facility_id: uuid.UUID,
    triaged_by: uuid.UUID,
) -> EmergencyTriage:
    """Records the initial triage of one emergency visit.

    A second initial triage of the same visit used to save, so one patient sat
    on the board twice at two acuities and the census counted two (QA 16 Oct
    2026). A change of acuity goes through re-triage, which keeps the reason.
    """
    from app.emergency.models import EmergencyTriage
    from app.opd.models import Visit

    visit = (
        await db.execute(select(Visit).where(Visit.id == payload.visit_id).with_for_update())
    ).scalar_one_or_none()
    if visit is None or visit.facility_id != facility_id or visit.patient_id != payload.patient_id:
        raise TriageRefused("visit_not_found", "This emergency visit was not found.", 404)
    if visit.visit_type != "emergency":
        raise TriageRefused("not_an_emergency_visit", "Only an emergency visit can be triaged here.", 422)

    existing = (
        await db.execute(
            select(EmergencyTriage.id).where(
                EmergencyTriage.visit_id == visit.id,
                EmergencyTriage.status.in_(ACTIVE_TRIAGE_STATUSES),
            )
        )
    ).first()
    if existing is not None:
        raise TriageRefused(
            "already_triaged",
            "This patient is already on the triage board. Use Re-triage to change the acuity.",
        )

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
    facility_id: uuid.UUID,
    changed_by: uuid.UUID,
) -> EmergencyTriage:
    """Updates acuity level with a mandatory clinical reasoning log entry."""
    from app.emergency.models import EmergencyTriageLog

    triage = await _triage_in_facility(db, triage_id, facility_id)
    if triage.status not in ACTIVE_TRIAGE_STATUSES:
        raise TriageRefused("triage_closed", "This patient has already left the emergency board.")
    if triage.acuity_level == payload.new_acuity:
        raise TriageRefused(
            "acuity_unchanged", "Choose a different acuity. The patient is already at this level.", 422,
        )

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
    facility_id: uuid.UUID,
    updated_by: uuid.UUID,
    updated_by_is_doctor: bool = False,
) -> EmergencyTriage:
    """Updates triage status, bed/bay, clinician, or disposition.

    Disposition rules (QA 16 Oct 2026): a patient who was seen cannot be
    "left without being seen"; one never seen cannot be admitted; discharging
    a P1/P2 patient needs an explicit confirmation; a finished triage is not
    reopened. An admit decision lands in the IPD To Admit queue as a clinical
    disposition, which is where the ward looks.
    """
    triage = await _triage_in_facility(db, triage_id, facility_id)
    now = datetime.now(timezone.utc)

    if triage.status not in ACTIVE_TRIAGE_STATUSES:
        raise TriageRefused("triage_closed", "This patient has already left the emergency board.")

    marking_seen = payload.clinician_seen or payload.status == "in_treatment"
    if marking_seen and triage.clinician_seen_at is None:
        triage.clinician_seen_at = now
        if triage.status == "waiting":
            triage.status = "in_treatment"
        # Mark Seen recorded no clinician, so the board said "No doctor
        # assigned" for a patient a doctor had just seen.
        if triage.assigned_doctor_id is None and updated_by_is_doctor:
            triage.assigned_doctor_id = updated_by

    if payload.assigned_doctor_id is not None:
        triage.assigned_doctor_id = payload.assigned_doctor_id
    if payload.assigned_bay is not None:
        triage.assigned_bay = payload.assigned_bay.strip() or None

    if payload.disposition is not None:
        seen = triage.clinician_seen_at is not None
        if payload.disposition == "lwbs" and seen:
            raise TriageRefused(
                "lwbs_after_seen",
                "This patient has been seen by a clinician, so they cannot be recorded as left without being seen.",
                422,
            )
        if payload.disposition == "admit" and not seen:
            raise TriageRefused(
                "admit_before_seen", "Mark the patient as seen by a clinician before admitting them.", 422,
            )
        if (
            payload.disposition == "discharge"
            and triage.acuity_level in HIGH_ACUITY
            and not payload.confirm_high_acuity_discharge
        ):
            raise TriageRefused(
                "high_acuity_discharge_unconfirmed",
                "This is a priority 1 or 2 patient. Confirm that discharging them home is intended.",
                422,
            )
        triage.disposition = payload.disposition
        triage.disposition_at = now
        if payload.disposition_notes is not None:
            triage.disposition_notes = payload.disposition_notes.strip() or None
        triage.status = {
            "discharge": "discharged", "transfer": "discharged", "admit": "admitted", "lwbs": "lwbs",
        }[payload.disposition]
        if payload.disposition in ("discharge", "transfer", "lwbs"):
            from app.opd.models import Visit

            visit = await db.get(Visit, triage.visit_id)
            if visit is not None and visit.status in ("registered", "in_consultation", "in_service", "waiting"):
                visit.status = "lwbs" if payload.disposition == "lwbs" else "completed"
        if payload.disposition == "admit":
            from app.admissions.service import create_clinical_disposition

            await create_clinical_disposition(
                db,
                facility_id=facility_id,
                patient_id=triage.patient_id,
                visit_id=triage.visit_id,
                disposition_type="admit",
                created_by=updated_by,
                priority="emergency" if triage.acuity_level in HIGH_ACUITY else "urgent",
                reason=triage.disposition_notes or triage.chief_complaint,
            )
    elif payload.status is not None and payload.status not in ("waiting", "in_treatment"):
        # Leaving the board without a disposition hid why the patient left.
        raise TriageRefused("disposition_required", "Record a disposition to close this triage.", 422)

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
    from app.opd.models import Visit
    from app.users.models import User
    from sqlalchemy import case

    acuity_order = case(
        (EmergencyTriage.acuity_level == "resuscitation", 1),
        (EmergencyTriage.acuity_level == "emergent", 2),
        (EmergencyTriage.acuity_level == "urgent", 3),
        else_=4,
    )

    query = (
        select(EmergencyTriage, Patient, User, Visit)
        .join(Patient, Patient.id == EmergencyTriage.patient_id)
        .join(Visit, Visit.id == EmergencyTriage.visit_id)
        .outerjoin(User, User.id == EmergencyTriage.assigned_doctor_id)
        .where(EmergencyTriage.facility_id == facility_id)
    )

    if status_filter:
        query = query.where(EmergencyTriage.status == status_filter)
    else:
        query = query.where(EmergencyTriage.status.in_(ACTIVE_TRIAGE_STATUSES))

    query = query.order_by(acuity_order, EmergencyTriage.triaged_at.asc())
    results = (await db.execute(query)).all()

    now = datetime.now(timezone.utc)
    items = []
    for triage, patient, doctor, visit in results:
        logs_stmt = (
            select(EmergencyTriageLog)
            .where(EmergencyTriageLog.triage_id == triage.id)
            .order_by(EmergencyTriageLog.changed_at.desc())
        )
        logs_result = (await db.execute(logs_stmt)).scalars().all()

        # Door-to-clinician runs from arrival (the visit), not from triage: a
        # patient who waited 11 minutes to be triaged showed 9 instead of 20.
        arrived_at = _aware(visit.created_at) or _aware(triage.triaged_at)
        clinician_seen_at = _aware(triage.clinician_seen_at)
        end = clinician_seen_at or now
        minutes_seen = max(0, int((end - arrived_at).total_seconds() / 60))

        items.append({
            "id": triage.id,
            "facility_id": triage.facility_id,
            "patient_id": triage.patient_id,
            "visit_id": triage.visit_id,
            "visit_number": visit.visit_number,
            "arrived_at": visit.created_at,
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
            "patient_identifier": patient.thid or patient.uhid,
            "patient_age_years": patient.age_years,
            "patient_sex": patient.sex,
            "doctor_name": doctor.full_name if doctor else None,
            "logs": logs_result,
        })
    return items


async def get_emergency_metrics(
    db: AsyncSession,
    facility_id: uuid.UUID,
) -> dict:
    """ED census and door-to-clinician.

    The census is every open emergency visit, triaged or not: an arrival
    waiting for triage is the patient most at risk of being missed, and the
    board used to count them as zero (QA 16 Oct 2026).
    """
    from app.emergency.models import EmergencyTriage
    from app.opd.models import Visit

    open_visits = (
        await db.execute(
            select(Visit.id, Visit.created_at).where(
                Visit.facility_id == facility_id,
                Visit.visit_type == "emergency",
                Visit.status.in_(["registered", "in_consultation"]),
            )
        )
    ).all()
    all_triages = (
        await db.execute(select(EmergencyTriage).where(EmergencyTriage.facility_id == facility_id))
    ).scalars().all()

    active = [t for t in all_triages if t.status in ACTIVE_TRIAGE_STATUSES]
    closed_visit_ids = {t.visit_id for t in all_triages if t.status not in ACTIVE_TRIAGE_STATUSES}
    active_visit_ids = {t.visit_id for t in active}
    untriaged = [v for v in open_visits if v.id not in active_visit_ids and v.id not in closed_visit_ids]
    waiting = [t for t in active if t.status == "waiting"]
    in_tx = [t for t in active if t.status == "in_treatment"]
    lwbs = [t for t in all_triages if t.status == "lwbs" or t.disposition == "lwbs"]

    arrivals = {
        v.id: _aware(v.created_at)
        for v in (
            await db.execute(
                select(Visit.id, Visit.created_at).where(
                    Visit.id.in_([t.visit_id for t in all_triages if t.clinician_seen_at is not None] or [uuid.uuid4()])
                )
            )
        ).all()
    }
    window_start = datetime.now(timezone.utc) - timedelta(hours=DOOR_TO_CLINICIAN_WINDOW_HOURS)
    door_times = []
    for t in all_triages:
        seen = _aware(t.clinician_seen_at)
        if seen is None or seen < window_start:
            continue
        arrived = arrivals.get(t.visit_id) or _aware(t.triaged_at)
        if seen >= arrived:
            door_times.append((seen - arrived).total_seconds() / 60)
    avg_door = (sum(door_times) / len(door_times)) if door_times else None

    return {
        "active_census": len(active) + len(untriaged),
        "waiting_count": len(waiting) + len(untriaged),
        "awaiting_triage_count": len(untriaged),
        "in_treatment_count": len(in_tx),
        "resuscitation_count": len([t for t in active if t.acuity_level == "resuscitation"]),
        "emergent_count": len([t for t in active if t.acuity_level == "emergent"]),
        "urgent_count": len([t for t in active if t.acuity_level == "urgent"]),
        "non_urgent_count": len([t for t in active if t.acuity_level == "non_urgent"]),
        "avg_door_to_clinician_minutes": round(avg_door, 1) if avg_door is not None else None,
        "door_to_clinician_window_hours": DOOR_TO_CLINICIAN_WINDOW_HOURS,
        "lwbs_count": len(lwbs),
    }
