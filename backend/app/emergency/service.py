"""Emergency identity logic — THID generation.

THID format: TH-FACILITY-YYMMDD-SEQ4
Example:     TH-JPR001-260714-0007  (docs/database-schema.md §3, 0006)

Mirrors patients/service.py's UHID sequence pattern (real Postgres SEQUENCE,
never MAX(col)+1, per schema-conventions.md §2.2) — but keyed per facility+day
instead of per facility+year, since emergency IDs are issued far more densely.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FACILITY_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def _current_day_str() -> str:
    return datetime.now(timezone.utc).strftime("%y%m%d")


def _thid_sequence_name(facility_code: str, day_str: str) -> str:
    if not _FACILITY_CODE_RE.match(facility_code):
        raise ValueError(f"facility_code contains invalid characters: {facility_code!r}")
    return f"seq_thid_{facility_code.lower()}_{day_str}"


async def _next_thid_sequence(db: AsyncSession, facility_code: str, day_str: str) -> int:
    seq_name = _thid_sequence_name(facility_code, day_str)
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
    result = await db.execute(text("SELECT nextval(:seq_name)"), {"seq_name": seq_name})
    return result.scalar()


async def generate_thid(db: AsyncSession, facility_code: str) -> str:
    day_str = _current_day_str()
    next_seq = await _next_thid_sequence(db, facility_code, day_str)
    seq_str = str(next_seq).zfill(4)
    return f"TH-{facility_code}-{day_str}-{seq_str}"
