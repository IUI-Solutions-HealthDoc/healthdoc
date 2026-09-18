"""HD-12: Stale-visit reconciliation — facility-timezone-aware, safe closure without destroying clinical/financial data."""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.business_date import get_business_date
from app.departments.models import Department
from app.opd.models import Encounter, Visit
from app.patients.models import Patient
from app.queue.models import QueueToken
from app.queue.schemas import (
    StaleVisitCandidateOut,
    StaleVisitsReconcileResult,
    StaleVisitsReportOut,
)
from app.users.models import Facility


async def get_stale_visits_candidates(
    db: AsyncSession,
    facility_id: uuid.UUID,
) -> StaleVisitsReportOut:
    """Retrieve all open OPD/teleconsult visits from prior business days.

    Excludes IPD admissions and Emergency triage visits strictly per HD-12 policy.
    """
    today_business_date = await get_business_date(db, facility_id)

    # Fetch facility timezone for date comparison
    fac = await db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")

    # Stale candidates: status in ('registered', 'in_consultation'), visit_type in ('opd', 'teleconsult')
    # and visit_date in facility timezone strictly earlier than today_business_date
    stmt = (
        select(
            Visit,
            Patient.full_name.label("patient_name"),
            Patient.uhid.label("patient_uhid"),
            Department.name.label("department_name"),
        )
        .join(Patient, Patient.id == Visit.patient_id)
        .outerjoin(Department, Department.id == Visit.department_id)
        .where(
            Visit.facility_id == facility_id,
            Visit.visit_type.in_(["opd", "teleconsult"]),
            Visit.status.in_(["registered", "in_consultation"]),
            func.date(func.timezone(Facility.timezone, Visit.visit_date)) < today_business_date,
        )
        .order_by(Visit.visit_date.asc())
    )

    rows = (await db.execute(stmt)).all()
    candidates: list[StaleVisitCandidateOut] = []

    for visit, patient_name, patient_uhid, department_name in rows:
        # Check for live token
        token_stmt = select(QueueToken).where(
            QueueToken.visit_id == visit.id,
            QueueToken.status.in_(["waiting", "called"]),
        )
        token = (await db.execute(token_stmt)).scalars().first()

        # Check for encounters
        enc_stmt = select(Encounter).where(Encounter.visit_id == visit.id)
        encounters = (await db.execute(enc_stmt)).scalars().all()
        has_active_encounter = any(e.ended_at is None for e in encounters)

        recommended_visit = "mark_lwbs" if visit.status == "registered" else "mark_closed"
        recommended_token = "mark_no_show" if token is not None else None

        candidate = StaleVisitCandidateOut(
            visit_id=visit.id,
            visit_number=visit.visit_number,
            patient_id=visit.patient_id,
            patient_name=patient_name or "Unknown",
            patient_uhid=patient_uhid or "",
            department_id=visit.department_id,
            department_name=department_name,
            visit_date=visit.visit_date,
            current_status=visit.status,
            live_token_id=token.id if token else None,
            live_token_display=token.token_display if token else None,
            live_token_status=token.status if token else None,
            encounter_count=len(encounters),
            has_active_encounter=has_active_encounter,
            recommended_visit_action=recommended_visit,
            recommended_token_action=recommended_token,
        )
        candidates.append(candidate)

    return StaleVisitsReportOut(
        total_stale_count=len(candidates),
        cutoff_date=today_business_date,
        candidates=candidates,
    )


async def reconcile_stale_visits(
    db: AsyncSession,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    visit_ids: list[uuid.UUID] | None = None,
    reason: str = "Authorized end-of-day stale visit reconciliation (LWBS / no-show)",
) -> StaleVisitsReconcileResult:
    """Safely reconcile unclosed visits from previous days without touching IPD/Emergency."""
    report = await get_stale_visits_candidates(db, facility_id)

    target_visit_ids = set(visit_ids) if visit_ids else None
    reconciled_ids: list[uuid.UUID] = []
    skipped_details: list[dict] = []

    for candidate in report.candidates:
        if target_visit_ids and candidate.visit_id not in target_visit_ids:
            continue

        visit = await db.get(Visit, candidate.visit_id)
        if not visit:
            skipped_details.append(
                {"visit_id": str(candidate.visit_id), "reason": "Visit not found"}
            )
            continue

        # Safeguard: Never auto-close IPD or Emergency
        if visit.visit_type in ("ipd", "emergency"):
            skipped_details.append(
                {
                    "visit_id": str(visit.id),
                    "reason": f"Visit type '{visit.visit_type}' is exempt from OPD reconciliation",
                }
            )
            continue

        # Idempotency: if already closed or terminal, skip
        if visit.status in ("completed", "lwbs", "cancelled", "closed"):
            skipped_details.append(
                {
                    "visit_id": str(visit.id),
                    "reason": f"Visit is already in terminal status '{visit.status}'",
                }
            )
            continue

        # Transition visit status
        if visit.status == "registered":
            visit.status = "lwbs"
        elif visit.status == "in_consultation":
            visit.status = "closed"

        visit.row_version = (visit.row_version or 1) + 1
        visit.updated_by = actor_id

        # Reconcile live token if any
        if candidate.live_token_id:
            token = await db.get(QueueToken, candidate.live_token_id)
            if token and token.status in ("waiting", "called"):
                token.status = "no_show"
                token.completed_at = func.now()

        reconciled_ids.append(visit.id)

    await db.flush()

    return StaleVisitsReconcileResult(
        reconciled_count=len(reconciled_ids),
        skipped_count=len(skipped_details),
        reconciled_visits=reconciled_ids,
        skipped_details=skipped_details,
    )
