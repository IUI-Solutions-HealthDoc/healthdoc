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
from sqlalchemy import text, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import encrypt_pii, aadhaar_blind_index, aadhaar_blind_indexes_all_versions, current_hmac_key_version, current_aes_key_version
from app.audit.actions import AuditAction
from app.audit.service import audited_mutation
from app.patients.models import Patient, PatientIdentifier, PatientMergeLog


_FACILITY_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def _identifier_to_checksum_string(uhid_body: str) -> str:
    """Converts an identifier (e.g. 'IN-RJ-JPR001-2026-000042') into a
    digit string for check-digit computation. Letters are mapped to two-digit
    numbers (A=10, B=11, ..., Z=35) so a letter-only typo (e.g. state code
    RJ vs MP) changes the check digit, not just digit-only typos.
    
    This is the IBAN/modulo-97 approach: every character contributes to the
    checksum, so the check digit catches typos anywhere in the identifier."""
    result = []
    for ch in uhid_body.replace("-", ""):  # strip dashes, keep letters and digits
        if ch.isdigit():
            result.append(ch)
        elif ch.isalpha():
            # A/a=10, B/b=11, ..., Z/z=35
            result.append(str(10 + (ord(ch.upper()) - ord('A'))))
        else:
            raise ValueError(f"Invalid character in identifier: {ch!r}")
    return "".join(result)


def compute_check_digit(uhid_body: str) -> str:
    """Computes a Luhn check digit over the full identifier (all letters and
    digits, no dashes), catching typos anywhere: state code, facility code,
    year, or sequence. Letters are mapped to 2-digit numbers (A=10 through
    Z=35) before Luhn is applied."""
    checksum_str = _identifier_to_checksum_string(uhid_body)
    
    total = 0
    reverse_digits = checksum_str[::-1]
    for i, ch in enumerate(reverse_digits):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return str(check)


def _extract_digits(uhid_without_check_digit: str) -> str:
    """Legacy helper — kept for backward compatibility. Extracts only digit
    characters (deprecated in favor of _identifier_to_checksum_string which
    also maps letters). Used by validate_uhid for the digit-only path."""
    return "".join(ch for ch in uhid_without_check_digit if ch.isdigit())


def validate_uhid(uhid: str) -> bool:
    """Recomputes the check digit over every character in the identifier
    (letters mapped to numbers, excluding the check digit itself) and
    compares. Catches typos anywhere: state code, facility code, year, or
    sequence. A check digit nobody verifies is decoration — this is the
    verifier the generator was missing."""
    if "-" not in uhid:
        return False
    body, _, check_digit = uhid.rpartition("-")
    if not check_digit.isdigit() or len(check_digit) != 1:
        return False
    try:
        recomputed = compute_check_digit(body)
    except ValueError:
        # Invalid character in the body
        return False
    return recomputed == check_digit


def _current_year_for_facility(facility_timezone: str) -> int:
    """Derives the current year in the facility's local timezone.

    Using UTC .year means patients registered between 00:00 and 05:30 IST
    on 1 January get last year's UHID — wrong forever, and they land on a
    different sequence (seq_uhid_<fac>_<wrong_year>). Schema doc rule:
    business dates must use facilities.timezone, never UTC directly.
    """
    import zoneinfo
    tz = zoneinfo.ZoneInfo(facility_timezone)
    return datetime.now(tz).year


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
    """Advance and return the next value from this facility+year UHID sequence.

    Sequences are pre-created at facility-insert time (Facility after_insert
    event in app/users/models.py) and for existing facilities by migration 0006.
    No DDL runs here — CREATE SEQUENCE inside a request path is not safe under
    concurrent first-registrations (IF NOT EXISTS is not atomic in Postgres).

    The except branch is a last-resort fallback for dev/test environments or
    facilities that predate the after_insert hook. It catches only
    undefined_object (pgcode 42P01) so genuine errors still surface.
    """
    from sqlalchemy.exc import ProgrammingError

    seq_name = _sequence_name(facility_code, year)
    try:
        result = await db.execute(
            text("SELECT nextval(:seq_name)"), {"seq_name": seq_name}
        )
        return result.scalar()
    except ProgrammingError as exc:
        pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
        if pgcode != "42P01":  # 42P01 = undefined_object
            raise
        # Sequence missing — create and retry once (dev/test fallback only).
        await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
        result = await db.execute(
            text("SELECT nextval(:seq_name)"), {"seq_name": seq_name}
        )
        return result.scalar()


async def generate_uhid(db: AsyncSession, state_code: str, facility_code: str, facility_timezone: str = "Asia/Kolkata") -> str:
    year = _current_year_for_facility(facility_timezone)
    next_seq = await _next_sequence(db, facility_code, year)
    seq_str = str(next_seq).zfill(6)
    # Check digit now covers every digit in the identifier (should-fix, PR
    # review), not just the sequence — a mistyped facility/state no longer
    # passes validation. IN/state/facility/year/seq are all fixed at this
    # point in the flow, so building the body first and extracting from it
    # keeps this in sync with validate_uhid() by construction.
    body = f"IN-{state_code}-{facility_code}-{year}-{seq_str}"
    check_digit = compute_check_digit(body)

    return f"{body}-{check_digit}"

def build_aadhaar_identifier(
    patient_id: uuid.UUID, aadhaar_number: str, captured_by: uuid.UUID,
) -> PatientIdentifier:
    """Builds (does not add/commit) the patient_identifiers row for Aadhaar.
    Caller adds it to the same session/transaction as the patient insert."""
    # HMAC and AES keys rotate independently (PR review blocker 7) — the
    # stored key_version column tracks the HMAC version specifically, since
    # that's what duplicate-check lookups depend on. AES decryption doesn't
    # need this column at all: it reads its own version byte from the
    # ciphertext blob (see security.py decrypt_pii).
    hmac_version = current_hmac_key_version()
    aes_version = current_aes_key_version()
    # Should-fix (PR review): bind the ciphertext to this row so a blob
    # copied from another patient's identifier can't decrypt cleanly here.
    # patient_id is already known (caller generates it before calling this),
    # identifier_type is always "aadhaar" for this function specifically.
    aad = f"{patient_id}:aadhaar".encode("utf-8")
    return PatientIdentifier(
        patient_id=patient_id,
        identifier_type="aadhaar",
        identifier_value_encrypted=encrypt_pii(aadhaar_number, key_version=aes_version, associated_data=aad),
        identifier_blind_index=aadhaar_blind_index(aadhaar_number, key_version=hmac_version),
        key_version=hmac_version,
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
    facility_id: uuid.UUID,
    full_name: str | None = None,
    dob=None,
    mobile: str | None = None,
    uhid: str | None = None,
    aadhaar_number: str | None = None,
    abha_number: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """Returns (page_of_(patient, score, matched_on), total_count).
    Exact-match paths (aadhaar/abha/uhid/mobile) run first; fuzzy name+dob fills in.
    A patient found via multiple paths keeps its highest-scoring match."""
    matches: dict = {}
    # facility_id is required (PR review blocker 4) — cross-facility search
    # is a separate, consent-gated operation, never a default. Unconditional
    # so a future caller can't accidentally reopen the leak by omitting it.
    # status != 'merged' (should-fix, PR review): a merged patient is a
    # tombstone — the target record has already absorbed it. Showing both
    # in results lets a receptionist pick the dead row by mistake.
    base_filter = [
        Patient.deleted_at.is_(None),
        Patient.facility_id == facility_id,
        Patient.status != "merged",
    ]

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
        # Should-fix (PR review): use the native % (similarity) operator
        # instead of func.similarity() — faster in Postgres since it can use
        # pg_trgm index acceleration. The % operator returns boolean (match or
        # not), not a score, so we also fetch the actual similarity score for
        # ranking. Set the threshold at Postgres level with SET LOCAL.
        similarity = func.similarity(Patient.full_name, full_name)
        stmt = (
            select(Patient, similarity.label("score"))
            .where(Patient.full_name.op("%")(full_name), *base_filter)
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

    # Pagination is intentionally in Python here (should-fix, PR review):
    # search_patients() runs up to 5 independent DB queries (aadhaar, abha,
    # uhid, mobile, name) and deduplicates across them, keeping the best
    # score per patient. This cross-path dedup is inherently a Python
    # operation — SQL can't express "run 5 queries, merge, keep highest score
    # per patient" without a complex CTE. The result set is already small
    # (name path is capped at .limit(50), exact paths return 0-5 rows each),
    # so in-memory sorting and slicing is not a performance concern here.
    # A future single-path-only search (e.g. name-only, no dedup needed)
    # could use DB-side LIMIT/OFFSET directly.
    ranked = sorted(matches.values(), key=lambda m: m[1], reverse=True)
    total = len(ranked)
    start = (page - 1) * page_size
    return ranked[start:start + page_size], total

async def find_duplicate_by_aadhaar(
    db: AsyncSession, *, aadhaar_number: str, facility_id: uuid.UUID,
) -> Patient | None:
    """Blocker 8: exact duplicate-check before registration. Checked across
    every active key version (aadhaar_blind_indexes_all_versions), same
    reasoning as search_patients's aadhaar path — a patient registered
    under an old key must still be found before a background re-index job
    catches up. Scoped to facility_id for the same reason search is
    (blocker 4): this is not a cross-facility lookup."""
    blind_indexes = list(aadhaar_blind_indexes_all_versions(aadhaar_number).values())
    stmt = (
        select(Patient)
        .join(PatientIdentifier, PatientIdentifier.patient_id == Patient.id)
        .where(
            PatientIdentifier.identifier_type == "aadhaar",
            PatientIdentifier.identifier_blind_index.in_(blind_indexes),
            Patient.facility_id == facility_id,
            Patient.deleted_at.is_(None),
            Patient.status != "merged",
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


# Columns that PATCH /patients/{id} is allowed to change.
# identity_path / identity_status / status / uhid / thid are deliberately
# excluded — those travel through dedicated workflows (ABHA verification,
# merge, UHID generation), not a generic update.
_PATIENT_UPDATEABLE_FIELDS: tuple[str, ...] = (
    "full_name", "sex", "dob", "age_years", "mobile", "abha_number",
    "guardian_name", "guardian_relationship",
    "address_line", "village_town", "district", "state_code", "pincode",
)


async def update_patient(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    payload: "PatientUpdate",
    updated_by: uuid.UUID,
    reason: str | None = None,
) -> Patient:
    """W2-03: update a patient record with full audit trail.

    Uses audited_mutation() (app/audit/service.py) rather than the automatic
    listener path for two reasons:
      1. The audit row needs a `reason` field, which the listener has no way
         to capture — it only sees column deltas, not request-level intent.
      2. Patient has not yet been added to listeners.AUDITABLE_MODULE_PREFIXES
         (that rollout is B7's — adding it unilaterally would double-write an
         audit row the moment B7 flips the switch). When that rollout happens,
         this explicit call and the opt-in attributes should be reviewed
         together.

    The audit row and the patient UPDATE share the same transaction via
    get_db() — if either fails, both roll back (see audit/service.py docstring).
    """
    from app.patients.schemas import PatientUpdate  # local import — avoids circular

    patient = await db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ValueError("patient_not_found")
    # Facility scoping — same rule as search (blocker 4): a receptionist at
    # facility A must never be able to update a patient registered at facility B,
    # even with a valid patient_id. Return 404 rather than 403 to avoid leaking
    # that the patient exists at another facility.
    if patient.facility_id != facility_id:
        raise ValueError("patient_not_found")
    if patient.status == "merged":
        raise ValueError("cannot_update_merged_patient")

    # Capture only the fields that are actually being changed, for old/new diff.
    fields_being_changed = [
        f for f in _PATIENT_UPDATEABLE_FIELDS
        if getattr(payload, f, None) is not None
    ]

    async with audited_mutation(
        db,
        facility_id=patient.facility_id,
        action=AuditAction.UPDATE,
        resource_type="patients",
        patient_id=patient.id,
    ) as audit:
        audit.resource_id = patient.id
        audit.old_value = {f: _json_safe_value(getattr(patient, f)) for f in fields_being_changed}
        audit.reason = reason

        for field in fields_being_changed:
            setattr(patient, field, getattr(payload, field))

        patient.updated_by = updated_by
        audit.new_value = {f: _json_safe_value(getattr(patient, f)) for f in fields_being_changed}

    await db.flush()
    await db.refresh(patient)
    return patient


def _json_safe_value(v: object) -> object:
    """Coerce date/UUID to strings so old_value/new_value are JSONB-serialisable.
    Mirrors listeners._json_safe() — kept local to avoid importing from audit
    until the Patient model fully opts into the listener rollout."""
    from datetime import date, datetime
    from uuid import UUID
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


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


# Tables that approve_merge actually repoints today. §3 0006 "Merge
# repointing" names the full list (visits, encounters, orders,
# prescriptions, lab_order_items, radiology_order_items, admissions,
# invoices, patient_identifiers, files, vitals, consent_records) — most of
# those tables don't exist yet (0007/0008/... land later). This set is
# checked against live FK metadata by
# test_patient_merge.py::test_repointing_covers_every_patient_fk, which
# fails the build the day a new FK to patients.id appears without a
# matching entry here. Do not add a table name here without also adding
# the repointing code for it below.
REPOINTED_ON_MERGE: frozenset[str] = frozenset(
    {"patient_identifiers", "visits", "ot_schedules", "fhir_bundle_transactions"}
)

# patient_merge_log itself has FKs to patients.id (source_patient_id,
# target_patient_id) — these must NEVER be repointed. It's the audit trail
# of the merge; rewriting its own references after the fact would let a
# merge erase evidence of which patient was actually merged into which.
AUDIT_TABLES_EXEMPT_FROM_REPOINTING: frozenset[str] = frozenset({"patient_merge_log"})

# Tables owned by other modules whose repointing code has not landed yet.
# When a module dev implements their repointing, they move their table
# from here into REPOINTED_ON_MERGE and add the code below. The test
# enforces this — nothing can silently slip through.
PENDING_REPOINT_OTHER_MODULES: frozenset[str] = frozenset({
    "allergies",      # allergies module — repointing owned by that module's dev
    "invoices",       # B7/0014 — repointing owned by the billing module's dev
    "orders",         # B3/0008 — see below; surfaced when app/orders became importable
    "prescriptions",  # B3/0008 — same
})
# visits and ot_schedules moved to REPOINTED_ON_MERGE (B3, #284).
#
# orders and prescriptions appear here now not because anything changed in
# 0008 but because app/orders/models.py finally imports — it referenced
# app.common.database and app.common.mixins, neither of which exists, so its
# models never registered on Base.metadata and this guard could not see their
# FKs to patients.id. They have been unrepointed since 0008 merged; only the
# detection is new.
#
# FOUR entries now. A merge currently succeeds while leaving the patient's
# allergies, invoices, orders and prescriptions attached to the merged-away
# record — orders and prescriptions being clinical history, not metadata.
# This set was a reasonable escape hatch at one entry. At four it is a merge
# that reports success and loses most of the record. Before adding a fifth,
# approve_merge should refuse outright while this set is non-empty.


async def approve_merge(
    db: AsyncSession,
    *,
    merge_log_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> "PatientMergeLog":
    from app.patients.models import PatientMergeLog
    from datetime import datetime, timezone

    # Blocker 6: lock the merge log row for the duration of this decision.
    # Without this, two supervisors approving the same request concurrently
    # both read status == "pending" and both proceed.
    merge_log = (
        await db.execute(
            select(PatientMergeLog).where(PatientMergeLog.id == merge_log_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not merge_log:
        raise ValueError("merge request not found")
    if merge_log.status != "pending":
        raise ValueError(f"merge request is not pending (status={merge_log.status})")
    if merge_log.requested_by == approved_by:
        raise ValueError("self_approval_not_allowed")  # maker-checker, matches /user-requests convention

    source = await db.get(Patient, merge_log.source_patient_id)
    target = await db.get(Patient, merge_log.target_patient_id)

    # Blocker 6: reject merging into a patient that is itself already a
    # merge tombstone. Without this, A->B then B->C leaves A pointing at a
    # dead row; single-hop resolution never reaches C.
    if target.status != "active":
        raise ValueError(
            f"target patient is not active (status={target.status}) — cannot merge into a "
            f"non-active patient; resolve the target's own merge chain first"
        )

    # Blocker 5: refuse to approve until every table with a real FK to
    # patients.id is covered by REPOINTED_ON_MERGE. A half-merge (source
    # tombstoned but child rows still pointing at it) is more dangerous
    # than no merge — /patients/{id}/history would silently return a
    # partial record. request_merge/reject_merge are unaffected and keep
    # shipping; only the destructive step is gated.
    missing = (
        _tables_with_fk_to_patients() - REPOINTED_ON_MERGE - AUDIT_TABLES_EXEMPT_FROM_REPOINTING - PENDING_REPOINT_OTHER_MODULES
    )
    if missing:
        raise NotImplementedError(
            f"merge_repointing_not_implemented: {sorted(missing)} reference patients.id "
            f"but are not yet repointed by approve_merge"
        )

    await _repoint_identifiers(db, source=source, target=target)
    await _repoint_visits(db, source=source, target=target)
    await _repoint_ot_schedules(db, source=source, target=target)
    await _repoint_fhir_bundle_transactions(db, source=source, target=target)

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


async def _repoint_identifiers(db: AsyncSession, *, source: Patient, target: Patient) -> None:
    """Moves source's patient_identifiers rows onto target (§3 0006 merge
    repointing rule). UNIQUE (patient_id, identifier_type) means a source
    row can't just be moved if target already has one of that type:

    - target has none of that type yet -> repoint (UPDATE patient_id)
    - target already has one, same blind index -> genuine duplicate
      (confirmed same underlying identifier); drop source's redundant row
    - target already has one, different blind index -> conflicting
      identity evidence. Refused rather than guessed at: silently picking
      one is exactly the kind of mistake this rule exists to prevent.
      Known limitation: blind-index comparison only works cleanly when
      both rows were hashed under the same HMAC key version — a rotation
      between the two registrations could make the same real identifier
      compare as different.
    """
    source_rows = (
        await db.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == source.id))
    ).scalars().all()
    if not source_rows:
        return

    target_rows = (
        await db.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == target.id))
    ).scalars().all()
    target_by_type = {row.identifier_type: row for row in target_rows}

    for row in source_rows:
        existing = target_by_type.get(row.identifier_type)
        if existing is None:
            row.patient_id = target.id
        elif existing.identifier_blind_index == row.identifier_blind_index:
            await db.delete(row)
        else:
            raise ValueError(
                f"identifier_conflict: source and target both have a "
                f"{row.identifier_type!r} identifier that do not match — "
                f"cannot auto-repoint, needs manual resolution before this "
                f"merge can be approved"
            )
    await db.flush()


async def _repoint_visits(db: AsyncSession, *, source: Patient, target: Patient) -> None:
    """Moves source's visits rows onto target (§3 0006 merge repointing
    rule). Unlike patient_identifiers, visits has no per-patient
    uniqueness constraint to collide with -- a visit is inherently a
    record of one clinical encounter, so every source visit simply
    moves to the target, no conflict case to detect. Without this,
    /patients/{id}/history for the target patient silently omits every
    visit (and everything hanging off it -- encounters, orders,
    diagnoses) that happened before the merge, exactly the "looks like
    it worked and quietly loses clinical history" failure mode this
    module's guard test exists to catch.
    """
    from app.opd.models import Visit

    await db.execute(
        update(Visit).where(Visit.patient_id == source.id).values(patient_id=target.id)
    )
    await db.flush()


async def _repoint_fhir_bundle_transactions(
    db: AsyncSession, *, source: Patient, target: Patient
) -> None:
    """Moves source's ABDM transmission records onto target.

    0026 created fhir_bundle_transactions with a patient_id FK and no
    repointing logic; the guard test only saw it once #367 registered the
    ORM model. Repointed rather than exempted: unlike patient_merge_log,
    which must never be rewritten because it is the evidence of the merge,
    this table records what was transmitted *about a person*, and after a
    merge that person is the target.

    0026's index is (patient_id, transmitted_at) and exists to answer "what
    was transmitted about this patient, and when" — the question a DPDP
    access request asks. Rows left on the dead source id make that answer
    incomplete for the surviving patient.

    Raw SQL rather than the ORM model on purpose: FhirBundleTransaction
    arrives with #367, and this module has to keep importing on branches
    without it. The table exists from 0026 either way.

    No uniqueness to collide with — a transmission is a point-in-time fact,
    so every source row simply moves.
    """
    await db.execute(
        text(
            "UPDATE fhir_bundle_transactions SET patient_id = :target_id "
            "WHERE patient_id = :source_id"
        ),
        {"target_id": target.id, "source_id": source.id},
    )
    await db.flush()


async def _repoint_ot_schedules(db: AsyncSession, *, source: Patient, target: Patient) -> None:
    """Moves source's ot_schedules rows onto target (§3 0006 merge
    repointing rule). Same shape as _repoint_visits: ot_schedules.
    patient_id has no per-patient uniqueness constraint, so every
    source row simply moves. Also B3-owned (0017, same as visits) --
    this branch's own migration introduced the FK, so it's this PR's
    job to keep the guard test (test_patient_merge.py) covering it
    rather than leaving a gap it just created.
    """
    from app.ot.models import OtSchedule

    await db.execute(
        update(OtSchedule).where(OtSchedule.patient_id == source.id).values(patient_id=target.id)
    )
    await db.flush()


def _tables_with_fk_to_patients() -> set[str]:
    """Every table currently registered on Base.metadata that has a
    ForeignKey column pointing at patients.id. Shared by approve_merge's
    guard and by the test that keeps it honest."""
    from app.common.db import Base

    tables = set()
    for table in Base.metadata.tables.values():
        if table.name == "patients":
            continue
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.target_fullname == "patients.id":
                    tables.add(table.name)
    return tables


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

    # Should-fix: don't overwrite the original request reason, and don't
    # set approved_by on a rejection — a populated approved_by on a
    # rejected request is misleading (implies someone approved it).
    merge_log.status = "rejected"
    merge_log.decision_reason = reason
    await db.flush()
    await db.refresh(merge_log)
    return merge_log
