"""
backend/app/opd/service.py

Business logic for visit creation and OPD lifecycle transitions.
Keeps the state machine in one place so the router stays thin and every
mutation goes through the shared audit middleware (schema doc §3-0003,
acceptance criteria: "Audit log written on mutations").

Changes in this revision:
  - business_date is now computed exactly ONCE, here, from
    facilities.timezone, and threaded into both the counter allocation
    (visit_number.next_visit_sequence) and the visit_number string.
    Previously visit_number.py computed its own date independently
    (hardcoded IST) while this module computed a separate one -- two
    clock reads for the same logical "today" that could disagree
    across a midnight boundary.
  - facilities.timezone is a live column (§3-0002, shipped in v3.9),
    not a v3.5 backlog item -- see visit_number.py's docstring for the
    full note on the stale backlog entry.
  - create_visit() now allocates its own sequence internally instead
    of receiving one from the router, since the sequence and the
    number string must share one business_date.
  - transition_visit_status() now bumps visit.row_version (§4A.2).
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd import visit_number
from app.opd.models import Visit
from app.opd.schemas import VisitCreate

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"in_consultation", "lwbs", "cancelled"},
    "in_consultation": {"completed", "cancelled", "closed"},
    "completed": {"closed"},
    "lwbs": set(),
    "cancelled": set(),
    "closed": set(),
}

REASON_REQUIRED_FOR = {"lwbs", "cancelled"}


class InvalidVisitTransition(Exception):
    """Raised when a status change breaks the OPD lifecycle rules."""

    def __init__(self, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"Cannot move visit from '{current_status}' to '{target_status}'"
        )


class MissingTransitionReason(Exception):
    """Raised when lwbs/cancelled is requested without a reason."""

    def __init__(self, target_status: str):
        self.target_status = target_status
        super().__init__(f"A reason is required to set status '{target_status}'")


def _business_date(facility_timezone: str) -> date:
    """
    (now() AT TIME ZONE f.timezone)::date, computed in Python. Never
    use datetime.now(timezone.utc) or CURRENT_DATE for any
    business-key date (§3 blanket rule). Returns a date object -- the
    single value shared by the counter allocation and the number
    string, so they can never disagree.
    """
    return datetime.now(ZoneInfo(facility_timezone)).date()


def _format_visit_number(facility_code: str, business_date: date, seq: int) -> str:
    """VST-<FACILITYCODE>-<YYYYMMDD>-<SEQ5> per schema doc §3-0007."""
    return f"VST-{facility_code}-{business_date:%Y%m%d}-{seq:05d}"


async def create_visit(
    db: AsyncSession,
    payload: VisitCreate,
    facility_code: str,
    facility_timezone: str,
    created_by: UUID,
) -> Visit:
    """
    Creates a new visit in 'registered' status. Allocates its own
    gapless sequence number (same pattern as billing_counters,
    §3-0014) using ONE business_date shared with the visit_number
    string -- see the module docstring for why this must not be two
    separate clock reads.
    """
    business_date = _business_date(facility_timezone)
    seq = await visit_number.next_visit_sequence(db, payload.facility_id, business_date)

    visit = Visit(
        visit_number=_format_visit_number(facility_code, business_date, seq),
        patient_id=payload.patient_id,
        facility_id=payload.facility_id,
        department_id=payload.department_id,
        visit_type=payload.visit_type,
        status="registered",
        visit_date=payload.visit_date,
        created_by=created_by,
    )
    db.add(visit)
    await db.flush()
    await db.refresh(visit)
    return visit


async def get_visit(db: AsyncSession, visit_id: UUID) -> Visit | None:
    result = await db.execute(select(Visit).where(Visit.id == visit_id))
    return result.scalar_one_or_none()


async def transition_visit_status(
    db: AsyncSession,
    visit: Visit,
    target_status: str,
    reason: str | None,
    updated_by: UUID,
) -> Visit:
    """
    Validates and applies an OPD lifecycle transition.
    Raises InvalidVisitTransition or MissingTransitionReason on rule
    violations -- the router maps these to the standard error envelope.
    """
    current_status = visit.status
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())

    if target_status not in allowed:
        raise InvalidVisitTransition(current_status, target_status)

    if target_status in REASON_REQUIRED_FOR and not reason:
        raise MissingTransitionReason(target_status)

    visit.status = target_status
    visit.updated_by = updated_by
    visit.row_version += 1

    await db.flush()
    await db.refresh(visit)
    return visit
