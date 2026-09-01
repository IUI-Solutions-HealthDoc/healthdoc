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
from app.integrations.abdm.fhir.service import build_encounter_close_bundles

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
    facility_id: UUID,
) -> Visit:
    """
    Creates a new visit in 'registered' status. Allocates its own
    gapless sequence number (same pattern as billing_counters,
    §3-0014) using ONE business_date shared with the visit_number
    string -- see the module docstring for why this must not be two
    separate clock reads.
    """
    business_date = _business_date(facility_timezone)
    # facility_id is the caller's, resolved from their token by the router --
    # never payload.facility_id. A receptionist at facility A must not be able
    # to open a visit (and its registration invoice) at facility B, which is
    # the same rule POST /patients already documents.
    seq = await visit_number.next_visit_sequence(db, facility_id, business_date)

    visit = Visit(
        visit_number=_format_visit_number(facility_code, business_date, seq),
        patient_id=payload.patient_id,
        facility_id=facility_id,
        department_id=payload.department_id,
        visit_type=payload.visit_type,
        status="registered",
        visit_date=payload.visit_date,
        created_by=created_by,
    )
    db.add(visit)
    await db.flush()
    await db.refresh(visit)

    # The visit's invoice (#389). Schema §3 0014: "one per visit, created at
    # registration with the registration-fee line" — billing.preview/build,
    # payment posting and the billing MIS all assume this row exists, and
    # _get_invoice_for_visit 404s without it. Nothing created one until now, so
    # every visit ever registered has an unusable billing chain.
    #
    # Same transaction as the visit and its counter, deliberately: a visit
    # without an invoice is precisely the state we are fixing, so it must not be
    # reachable by a failure between two commits. Imported here rather than at
    # module scope to keep opd -> billing from becoming an import cycle.
    #
    # Shares this request's single business_date, so the visit number and the
    # invoice number cannot be stamped with different days across midnight.
    from app.billing.service import create_registration_invoice

    await create_registration_invoice(
        db,
        visit_id=visit.id,
        patient_id=visit.patient_id,
        facility_id=visit.facility_id,
        business_date=business_date,
        created_by=created_by,
    )
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

    if target_status == "closed":
        await build_encounter_close_bundles(db, visit)

    await db.flush()
    await db.refresh(visit)
    return visit


class InvalidVisitTypeChange(Exception):
    """A reclassification the data will not support."""


async def change_visit_type(
    db: AsyncSession,
    *,
    visit,
    new_type: str,
    reason: str,
    updated_by,
):
    """Reclassify a visit, refusing the changes that would strand a bed.

    The one rule that matters: a visit currently occupying a bed cannot be
    moved to a type that does not occupy one while that admission is still
    open. Allowing it would leave an `admissions` row pointing at a bed for a
    visit the ward census no longer counts — the bed reads occupied forever and
    only a manual SQL fix clears it.

    Moving INTO a bed-occupying type is allowed and deliberately does not
    create an admission. Admitting is a separate clinical act with a ward, a
    bed and a reason; silently allocating one here would put a patient in a bed
    nobody chose.
    """
    from sqlalchemy import select

    from app.admissions.models import Admission
    from app.common.enums import AdmissionStatus, VisitType

    valid = {t.value for t in VisitType}
    if new_type not in valid:
        raise InvalidVisitTypeChange(
            f"{new_type!r} is not a visit type. Expected one of: {', '.join(sorted(valid))}"
        )
    if new_type == visit.visit_type:
        raise InvalidVisitTypeChange(f"Visit is already {new_type!r}")

    bed_types = VisitType.bed_occupying()
    if visit.visit_type in bed_types and new_type not in bed_types:
        open_admission = (
            await db.execute(
                select(Admission).where(
                    Admission.visit_id == visit.id,
                    # TRANSFERRED counts as occupying too — the patient moved
                    # to a different bed, they did not leave. Checking only
                    # ADMITTED would let a transferred patient be reclassified
                    # out of IPD while still lying in a bed.
                    Admission.status.in_(
                        (AdmissionStatus.ADMITTED.value, AdmissionStatus.TRANSFERRED.value)
                    ),
                )
            )
        ).scalar_one_or_none()
        if open_admission is not None:
            raise InvalidVisitTypeChange(
                f"This visit still occupies a bed. Discharge the admission before "
                f"reclassifying it from {visit.visit_type!r} to {new_type!r}, or the "
                f"bed stays allocated to a visit the ward no longer counts."
            )

    previous = visit.visit_type
    visit.visit_type = new_type
    visit.updated_by = updated_by
    visit.row_version += 1
    await db.flush()
    return visit, previous
