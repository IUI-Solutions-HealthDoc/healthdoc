"""
backend/app/opd/service.py

Business logic for visit creation and OPD lifecycle transitions.
Keeps the state machine in one place so the router stays thin and every
mutation goes through the shared audit middleware (schema doc §3-0003,
acceptance criteria: "Audit log written on mutations").
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Visit
from app.opd.schemas import VisitCreate

# --------------------------------------------------------------------------
# OPD lifecycle rules
# --------------------------------------------------------------------------
# Allowed transitions: current_status -> set of statuses it may move to.
# A visit can only ever move forward or into a terminal "did not complete"
# state — never backward, and never skip a state.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"in_consultation", "lwbs", "cancelled"},
    "in_consultation": {"completed", "cancelled"},
    "completed": set(),   # terminal
    "lwbs": set(),        # terminal
    "cancelled": set(),   # terminal
}

# Statuses that require a `reason` to be recorded (audit/compliance trail).
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


def _generate_visit_number(facility_code: str, seq: int) -> str:
    """VST-<FACILITYCODE>-<YYYYMMDD>-<SEQ5> per schema doc §3-0007."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"VST-{facility_code}-{today}-{seq:05d}"


async def create_visit(
    db: AsyncSession,
    payload: VisitCreate,
    facility_code: str,
    next_sequence: int,
    created_by: UUID,
) -> Visit:
    """
    Creates a new visit in 'registered' status.
    next_sequence should come from a gapless counter, same pattern as
    billing_counters (§3-0014) -- pass it in rather than computing it here
    so callers can wrap the whole thing in one transaction with row locking.
    """
    visit = Visit(
        visit_number=_generate_visit_number(facility_code, next_sequence),
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
    # The audit middleware picks up this UPDATE automatically (old_value /
    # new_value diff) -- no manual audit_logs insert needed here.

    await db.flush()
    await db.refresh(visit)
    return visit