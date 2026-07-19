"""Patient identity logic — UHID generation (B2-W1-02).

UHID format: IN-STATE-FACILITY-YEAR-SEQ-CHECKDIGIT
Example:     IN-RJ-JPR001-2026-000042-7
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.patients.models import Patient


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


async def _next_sequence(db: AsyncSession, prefix: str) -> int:
    result = await db.execute(
        select(func.max(Patient.uhid)).where(Patient.uhid.like(f"{prefix}%"))
    )
    last_uhid = result.scalar()
    if last_uhid is None:
        return 1
    seq_part = last_uhid.rsplit("-", 2)[-2]
    return int(seq_part) + 1


async def generate_uhid(db: AsyncSession, state_code: str, facility_code: str) -> str:
    year = _current_year()
    prefix = f"IN-{state_code}-{facility_code}-{year}-"

    next_seq = await _next_sequence(db, prefix)
    seq_str = str(next_seq).zfill(6)
    check_digit = compute_check_digit(seq_str)

    return f"{prefix}{seq_str}-{check_digit}"
