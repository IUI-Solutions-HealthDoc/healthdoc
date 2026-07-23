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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.security import encrypt_pii, aadhaar_blind_index, current_key_version
from app.patients.models import PatientIdentifier

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