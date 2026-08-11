"""The one correct way to allocate a lab or radiology accession number.

Repo path: backend/app/common/accession.py

Format is frozen by schema-conventions.md §2.2:
    LAB-<YYYYMMDD>-<SEQ5>    RAD-<YYYYMMDD>-<SEQ5>

WHY THIS EXISTS
---------------
Both pathology and radiology previously allocated their own, identically:

    count_today = SELECT count(*) ... WHERE accession_number LIKE 'LAB-<date>-%'
    seq = count_today + 1

§2.2 names that exact pattern: "Never MAX(col)+1 — it races." Two concurrent
requests read the same count and build the same number; the UNIQUE index
then rejects one of them, so the visible symptom is a failed order rather
than a duplicate. It also *reuses* a number after any delete, and accession
numbers get printed on specimen labels — the same identifier appearing on
two different samples is the failure that matters clinically.

WHY A COUNTERS ROW RATHER THAN A SEQUENCE
-----------------------------------------
§2.2 reserves counters tables for gapless financial numbering and puts
everything else on a Postgres sequence. Accession numbers don't need to be
gapless, but their frozen format resets daily and a sequence cannot reset
itself. See 0020a's docstring for the alternatives considered.

INSERT ... ON CONFLICT DO UPDATE ... RETURNING, not SELECT ... FOR UPDATE:
FOR UPDATE can only lock a row that already exists, which leaves the first
allocation of each day racing on the INSERT. Same reasoning Vani applied in
billing's _allocate_billing_number.
"""
from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.business_date import get_business_date

# Lightweight table clause rather than importing an ORM model: this is the
# only code that touches accession_counters, and a model would need an owner
# module that doesn't exist. Same approach as billing's billing_counters_t.
accession_counters_t = sa.table(
    "accession_counters",
    sa.column("prefix"),
    sa.column("counter_date"),
    sa.column("last_value"),
)

LAB = "LAB"
RADIOLOGY = "RAD"


async def allocate_accession_number(
    db: AsyncSession, *, prefix: str, facility_id: uuid.UUID
) -> str:
    """Allocate the next accession number for `prefix` on the facility's
    current business date.

    The date comes from get_business_date (i.e. now() AT TIME ZONE
    facilities.timezone), not UTC. Between 00:00 and 05:30 IST a UTC date
    is still yesterday, which would file a sample under the wrong day and
    restart the day's numbering hours late.

    No commit here — the number is allocated in the caller's transaction,
    so a rolled-back order does not consume one.
    """
    if prefix not in (LAB, RADIOLOGY):
        raise ValueError(f"unknown accession prefix {prefix!r}; expected LAB or RAD")

    business_date: date = await get_business_date(db, facility_id)

    upsert = (
        pg_insert(accession_counters_t)
        .values(prefix=prefix, counter_date=business_date, last_value=1)
        .on_conflict_do_update(
            constraint="uq_accession_counters_prefix_date",
            set_={"last_value": accession_counters_t.c.last_value + 1},
        )
        .returning(accession_counters_t.c.last_value)
    )
    sequence = (await db.execute(upsert)).scalar_one()

    return f"{prefix}-{business_date:%Y%m%d}-{sequence:05d}"
