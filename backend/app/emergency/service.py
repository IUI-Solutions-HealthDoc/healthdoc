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
from datetime import datetime

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
