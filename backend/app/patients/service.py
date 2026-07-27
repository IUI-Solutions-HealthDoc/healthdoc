"""Patient identity logic — UHID generation (B2-W1-02).

UHID format: IN-STATE-FACILITY-YEAR-SEQ-CHECKDIGIT
Example:     IN-RJ-JPR001-2026-000042-7

Per schema-conventions.md §2.2: sequence numbers come from a real Postgres
SEQUENCE, one per facility+year (seq_uhid_<facility_code>_<year>), never
MAX(col)+1. Sequences are atomic under concurrency by construction — no
advisory lock needed, and no serialization of concurrent registrations.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import uuid
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import encrypt_pii, aadhaar_blind_index, aadhaar_blind_indexes_all_versions, current_key_version
from app.patients.models import Patient, PatientIdentifier


_FACILITY_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def compute_check_digit(digits: str) -> str:
    if not digits.isdigit():
        raise ValueError("compute_check_digit expects a numeric string")

    total = 0
    reverse_digits = digits[::-1]
    for i, ch in enumerate(reverse_digits):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return str(check)


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _sequence_name(facility_code: str, year: int) -> str:
    """seq_uhid_<facility_code>_<year>, matching schema-conventions.md §2.2's
    naming example. facility_code is validated against a strict charset
    before being interpolated into DDL — CREATE SEQUENCE cannot take the
    name as a bind parameter, so this validation is the only thing standing
    between a malformed facility.code and SQL injection into a DDL string."""
    if not _FACILITY_CODE_RE.match(facility_code):
        raise ValueError(f"facility_code contains invalid characters: {facility_code!r}")
    return f"seq_uhid_{facility_code.lower()}_{year}"


async def _next_sequence(db: AsyncSession, facility_code: str, year: int) -> int:
    seq_name = _sequence_name(facility_code, year)

    # DDL: identifier cannot be parametrized, hence the regex validation above.
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))

    # DML: nextval() takes a regclass — the sequence name here IS a bind
    # parameter value (implicitly cast to regclass), not a raw identifier,
    # so this call is fully injection-safe regardless of facility_code.
    result = await db.execute(text("SELECT nextval(:seq_name)"), {"seq_name": seq_name})
    return result.scalar()


async def generate_uhid(db: AsyncSession, state_code: str, facility_code: str) -> str:
    year = _current_year()
    next_seq = await _next_sequence(db, facility_code, year)
    seq_str = str(next_seq).zfill(6)
    check_digit = compute_check_digit(seq_str)

    return f"IN-{state_code}-{facility_code}-{year}-{seq_str}-{check_digit}"

def build_aadhaar_identifier(
    patient_id: uuid.UUID, aadhaar_number: str, captured_by: uuid.UUID,
) -> PatientIdentifier:
    """Builds (does not add/commit) the patient_identifiers row for Aadhaar.
    Caller adds it to the same session/transaction as the patient insert."""
    version = current_key_version()
    return PatientIdentifier(
        patient_id=patient_id,
        identifier_type="aadhaar",
        identifier_value_encrypted=encrypt_pii(aadhaar_number, key_version=version),
        identifier_blind_index=aadhaar_blind_index(aadhaar_number, key_version=version),
        key_version=version,
        captured_by=captured_by,
    )

NAME_TRGM_THRESHOLD = 0.3  # tunable threshold, not specified in the schema docs — revisit if match quality looks off

def mask_mobile(mobile: str | None) -> str | None:
    if not mobile:
        return None
    if len(mobile) <= 4:
        return "*" * len(mobile)
    return "*" * (len(mobile) - 4) + mobile[-4:]


async def search_patients(
    db: AsyncSession,
    *,
    full_name: str | None = None,
    dob=None,
    mobile: str | None = None,
    uhid: str | None = None,
    aadhaar_number: str | None = None,
    abha_number: str | None = None,
    facility_id=None,
    page: int = 1,
    page_size: int = 20,
):
    """Returns (page_of_(patient, score, matched_on), total_count).
    Exact-match paths (aadhaar/abha/uhid/mobile) run first; fuzzy name+dob fills in.
    A patient found via multiple paths keeps its highest-scoring match."""
    matches: dict = {}
    base_filter = [Patient.deleted_at.is_(None)]
    if facility_id:
        base_filter.append(Patient.facility_id == facility_id)

    if aadhaar_number:
        blind_indexes = list(aadhaar_blind_indexes_all_versions(aadhaar_number).values())
        stmt = (
            select(Patient)
            .join(PatientIdentifier, PatientIdentifier.patient_id == Patient.id)
            .where(
                PatientIdentifier.identifier_type == "aadhaar",
                PatientIdentifier.identifier_blind_index.in_(blind_indexes),
                *base_filter,
            )
        )
        for patient in (await db.execute(stmt)).scalars().all():
            matches[patient.id] = (patient, 1.0, "aadhaar")

    if abha_number:
        stmt = select(Patient).where(Patient.abha_number == abha_number, *base_filter)
        for patient in (await db.execute(stmt)).scalars().all():
            existing = matches.get(patient.id)
            if not existing or existing[1] < 1.0:
                matches[patient.id] = (patient, 1.0, "abha")

    if uhid:
        stmt = select(Patient).where(Patient.uhid == uhid, *base_filter)
        for patient in (await db.execute(stmt)).scalars().all():
            existing = matches.get(patient.id)
            if not existing or existing[1] < 1.0:
                matches[patient.id] = (patient, 1.0, "uhid")

    if mobile:
        stmt = select(Patient).where(Patient.mobile == mobile, *base_filter)
        for patient in (await db.execute(stmt)).scalars().all():
            existing = matches.get(patient.id)
            if not existing or existing[1] < 1.0:
                matches[patient.id] = (patient, 1.0, "mobile")

    if full_name:
        similarity = func.similarity(Patient.full_name, full_name)
        stmt = (
            select(Patient, similarity.label("score"))
            .where(similarity > NAME_TRGM_THRESHOLD, *base_filter)
            .order_by(similarity.desc())
            .limit(50)
        )
        for patient, score in (await db.execute(stmt)).all():
            boosted = float(score)
            if dob and patient.dob == dob:
                boosted = min(1.0, boosted + 0.3)
            existing = matches.get(patient.id)
            if not existing or existing[1] < boosted:
                matches[patient.id] = (patient, boosted, "name_dob")

    ranked = sorted(matches.values(), key=lambda m: m[1], reverse=True)
    total = len(ranked)
    start = (page - 1) * page_size
    return ranked[start:start + page_size], total

def _patient_snapshot(patient: "Patient") -> dict:
    """Minimal before/after snapshot for patient_merge_log — captures only the
    fields the merge action itself can change, not full PHI."""
    return {
        "id": str(patient.id),
        "uhid": patient.uhid,
        "thid": patient.thid,
        "status": patient.status,
        "merged_into_patient_id": str(patient.merged_into_patient_id) if patient.merged_into_patient_id else None,
    }


async def request_merge(
    db: AsyncSession,
    *,
    source_patient_id: uuid.UUID,
    target_patient_id: uuid.UUID,
    source_type: str,
    reason: str | None,
    requested_by: uuid.UUID,
) -> "PatientMergeLog":
    from app.patients.models import PatientMergeLog

    if source_patient_id == target_patient_id:
        raise ValueError("source_patient_id and target_patient_id must differ")

    source = await db.get(Patient, source_patient_id)
    target = await db.get(Patient, target_patient_id)
    if not source or not target:
        raise ValueError("source or target patient not found")

    merge_log = PatientMergeLog(
        source_type=source_type,
        source_patient_id=source_patient_id,
        target_patient_id=target_patient_id,
        requested_by=requested_by,
        status="pending",
        reason=reason,
        before_snapshot={"source": _patient_snapshot(source), "target": _patient_snapshot(target)},
    )
    db.add(merge_log)
    await db.flush()
    await db.refresh(merge_log)
    return merge_log


async def approve_merge(
    db: AsyncSession,
    *,
    merge_log_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> "PatientMergeLog":
    from app.patients.models import PatientMergeLog
    from datetime import datetime, timezone

    merge_log = await db.get(PatientMergeLog, merge_log_id)
    if not merge_log:
        raise ValueError("merge request not found")
    if merge_log.status != "pending":
        raise ValueError(f"merge request is not pending (status={merge_log.status})")
    if merge_log.requested_by == approved_by:
        raise ValueError("self_approval_not_allowed")  # maker-checker, matches /user-requests convention

    source = await db.get(Patient, merge_log.source_patient_id)
    target = await db.get(Patient, merge_log.target_patient_id)

    source.status = "merged"
    source.merged_into_patient_id = target.id
    await db.flush()

    merge_log.status = "approved"
    merge_log.approved_by = approved_by
    merge_log.approved_at = datetime.now(timezone.utc)
    merge_log.after_snapshot = {"source": _patient_snapshot(source), "target": _patient_snapshot(target)}
    await db.flush()
    await db.refresh(merge_log)
    return merge_log


async def reject_merge(
    db: AsyncSession,
    *,
    merge_log_id: uuid.UUID,
    rejected_by: uuid.UUID,
    reason: str | None,
) -> "PatientMergeLog":
    from app.patients.models import PatientMergeLog

    merge_log = await db.get(PatientMergeLog, merge_log_id)
    if not merge_log:
        raise ValueError("merge request not found")
    if merge_log.status != "pending":
        raise ValueError(f"merge request is not pending (status={merge_log.status})")
    if merge_log.requested_by == rejected_by:
        raise ValueError("self_approval_not_allowed")

    merge_log.status = "rejected"
    merge_log.approved_by = rejected_by
    merge_log.reason = reason or merge_log.reason
    await db.flush()
    await db.refresh(merge_log)
    return merge_log
