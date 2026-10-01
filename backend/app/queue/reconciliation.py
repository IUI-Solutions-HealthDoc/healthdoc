"""HD-12: Stale-visit reconciliation — facility-timezone-aware, safe closure without destroying clinical/financial data."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.common.business_date import get_business_date
from app.common.enums import QueueTokenStatus
from app.departments.models import Department
from app.opd import service as opd_service
from app.opd.models import Encounter, Visit
from app.patients.models import Patient
from app.queue.models import QueueToken
from app.queue.schemas import (
    StaleVisitCandidateOut,
    StaleVisitsReconcileResult,
    StaleVisitsReportOut,
)
from app.queue.service import LIVE_TOKEN_STATUSES, end_live_tokens_for_visit
from app.users.models import Facility

RECONCILABLE_VISIT_TYPES = ("opd", "teleconsult")

#: registered -> lwbs and in_consultation -> closed are both edges of
#: app.opd.service.ALLOWED_TRANSITIONS; nothing else is reconciled.
RECONCILE_TARGET = {"registered": "lwbs", "in_consultation": "closed"}


def _stale_visits_query(facility_id: uuid.UUID, today_business_date):
    # Facility is joined on the visit's own facility. Referencing
    # Facility.timezone without a join cross-joined every facility, repeating
    # each candidate once per facility and comparing against the wrong zones.
    return (
        select(Visit)
        .join(Facility, Facility.id == Visit.facility_id)
        .where(
            Visit.facility_id == facility_id,
            Visit.visit_type.in_(RECONCILABLE_VISIT_TYPES),
            Visit.status.in_(tuple(RECONCILE_TARGET)),
            func.date(func.timezone(Facility.timezone, Visit.visit_date)) < today_business_date,
        )
    )


async def get_stale_visits_candidates(
    db: AsyncSession,
    facility_id: uuid.UUID,
) -> StaleVisitsReportOut:
    """Retrieve all open OPD/teleconsult visits from prior business days.

    Excludes IPD admissions and Emergency triage visits strictly per HD-12 policy.
    """
    today_business_date = await get_business_date(db, facility_id)

    base = _stale_visits_query(facility_id, today_business_date).subquery()
    stmt = (
        select(
            Visit,
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            Patient.thid.label("patient_thid"),
            Department.name.label("department_name"),
            Department.name_hi.label("department_name_hi"),
        )
        .join(base, base.c.id == Visit.id)
        .join(Patient, Patient.id == Visit.patient_id)
        .outerjoin(Department, Department.id == Visit.department_id)
        .order_by(Visit.visit_date.asc())
    )

    rows = (await db.execute(stmt)).all()
    candidates: list[StaleVisitCandidateOut] = []

    for visit, patient_name, patient_uhid, patient_thid, department_name, department_name_hi in rows:
        token = (
            await db.execute(
                select(QueueToken).where(
                    QueueToken.visit_id == visit.id,
                    QueueToken.status.in_(LIVE_TOKEN_STATUSES),
                )
            )
        ).scalars().first()

        encounters = (
            await db.execute(select(Encounter).where(Encounter.visit_id == visit.id))
        ).scalars().all()
        has_active_encounter = any(e.ended_at is None for e in encounters)

        candidates.append(
            StaleVisitCandidateOut(
                visit_id=visit.id,
                visit_number=visit.visit_number,
                patient_id=visit.patient_id,
                patient_name=patient_name or "Unknown",
                patient_uhid=patient_uhid or patient_thid or "",
                department_id=visit.department_id,
                department_name=department_name,
                department_name_hi=department_name_hi,
                visit_date=visit.visit_date,
                current_status=visit.status,
                live_token_id=token.id if token else None,
                live_token_display=token.token_display if token else None,
                live_token_status=token.status if token else None,
                encounter_count=len(encounters),
                has_active_encounter=has_active_encounter,
                recommended_visit_action=(
                    "mark_lwbs" if visit.status == "registered" else "mark_closed"
                ),
                recommended_token_action="mark_no_show" if token is not None else None,
            )
        )

    return StaleVisitsReportOut(
        total_stale_count=len(candidates),
        cutoff_date=today_business_date,
        candidates=candidates,
    )


async def reconcile_stale_visits(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
    visit_ids: list[uuid.UUID] | None = None,
) -> StaleVisitsReconcileResult:
    """Close stale OPD/teleconsult visits through the OPD state machine.

    `visit_ids=None` means every stale visit; the router only allows that when
    the caller asked for it explicitly. Each visit is re-read under lock and
    re-checked, because the candidate list may be minutes old.
    """
    today_business_date = await get_business_date(db, facility_id)
    stmt = _stale_visits_query(facility_id, today_business_date)
    if visit_ids is not None:
        stmt = stmt.where(Visit.id.in_(visit_ids))
    visits = (
        await db.execute(stmt.order_by(Visit.id).with_for_update(of=Visit))
    ).scalars().all()

    found = {visit.id for visit in visits}
    skipped_details: list[dict] = [
        {"visit_id": str(visit_id), "reason": "Not a stale open OPD visit at this facility"}
        for visit_id in (visit_ids or [])
        if visit_id not in found
    ]
    reconciled_ids: list[uuid.UUID] = []

    for visit in visits:
        previous_status = visit.status
        target = RECONCILE_TARGET[previous_status]

        # A patient who waited and left is a no-show on the queue, not a
        # cancellation; ending the token first also leaves nothing live for
        # the state machine's own token handling to find.
        ended_tokens = await end_live_tokens_for_visit(
            db, visit.id, QueueTokenStatus.NO_SHOW.value
        )
        try:
            await opd_service.transition_visit_status(
                db, visit, target, reason=reason, updated_by=actor_id
            )
        except opd_service.InvalidVisitTransition as exc:
            skipped_details.append({"visit_id": str(visit.id), "reason": str(exc)})
            continue

        await write_audit_log(
            db,
            facility_id=facility_id,
            action="update",
            resource_type="visits",
            resource_id=visit.id,
            patient_id=visit.patient_id,
            visit_id=visit.id,
            user_id=actor_id,
            old_value={"status": previous_status},
            new_value={
                "status": target,
                "tokens_marked_no_show": [str(token.id) for token in ended_tokens],
            },
            reason=f"Stale-visit reconciliation: {reason}",
        )
        reconciled_ids.append(visit.id)

    return StaleVisitsReconcileResult(
        reconciled_count=len(reconciled_ids),
        skipped_count=len(skipped_details),
        reconciled_visits=reconciled_ids,
        skipped_details=skipped_details,
    )
