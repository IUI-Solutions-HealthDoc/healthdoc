"""backend/app/nursing/router.py -- /nursing endpoints (#390).

0023 created vitals, intake_output_records and the handover tables in July;
this module was a `/ping` stub until now, so none of it could be read or
written over the API. #193 (vitals chart + eMAR) and #210 (nurse task queue)
were blocked on it.

There is no DELETE. A nursing observation is a clinical record: corrections go
through a new entry, so the original and the correction are both visible.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Ward
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.nursing import incidents, service
from app.nursing.schemas import (
    FluidBalanceOut, IncidentOut, IncidentReport, IncidentReviewRequest,
    IntakeOutputCreate, IntakeOutputOut,
    MedicationAdministrationCreate, MedicationAdministrationOut,
    OrderCompleteRequest, OrderTaskOut, VitalsCreate, VitalsOut,
)
from app.opd.models import Encounter, Visit
from app.orders.models import Order, Prescription, PrescriptionItem
from app.patients.models import Patient

router = APIRouter(prefix="/nursing", tags=["nursing"])

#: Who records observations at the bedside. Doctors included because in a small
#: facility the doctor often takes the observation themselves.
_RECORD_ROLES = ("nurse", "doctor", "admin")
_READ_ROLES = ("nurse", "doctor", "pharmacist", "admin")


async def _require_patient_scope(
    db: AsyncSession, patient_id: UUID, facility_id: UUID
) -> None:
    exists = (
        await db.execute(
            select(Patient.id).where(
                Patient.id == patient_id,
                Patient.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Patient not found")


async def _require_admission_scope(
    db: AsyncSession,
    admission_id: UUID,
    facility_id: UUID,
    *,
    patient_id: UUID | None = None,
) -> None:
    statement = (
        select(Admission.id)
        .join(Ward, Ward.id == Admission.ward_id)
        .where(Admission.id == admission_id, Ward.facility_id == facility_id)
    )
    if patient_id is not None:
        statement = statement.where(Admission.patient_id == patient_id)
    exists = (await db.execute(statement)).scalar_one_or_none()
    if exists is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Admission not found")


async def _require_encounter_scope(
    db: AsyncSession,
    encounter_id: UUID,
    patient_id: UUID,
    facility_id: UUID,
) -> None:
    exists = (
        await db.execute(
            select(Encounter.id)
            .join(Visit, Visit.id == Encounter.visit_id)
            .where(
                Encounter.id == encounter_id,
                Encounter.facility_id == facility_id,
                Visit.patient_id == patient_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Encounter not found")


async def _require_prescription_item_for_patient(
    db: AsyncSession,
    prescription_item_id: UUID,
    patient_id: UUID,
    facility_id: UUID,
) -> None:
    exists = (
        await db.execute(
            select(PrescriptionItem.id)
            .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
            .where(
                PrescriptionItem.id == prescription_item_id,
                Prescription.patient_id == patient_id,
                Prescription.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Prescription item not found")


async def _require_order_scope(
    db: AsyncSession, order_id: UUID, facility_id: UUID
) -> None:
    exists = (
        await db.execute(
            select(Order.id).where(Order.id == order_id, Order.facility_id == facility_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "order_not_found")


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "nursing", "status": "ok"}


@router.post(
    "/vitals",
    response_model=VitalsOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_RECORD_ROLES))],
)
async def create_vitals(
    payload: VitalsCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> VitalsOut:
    await _require_patient_scope(db, payload.patient_id, current_db_user.facility_id)
    if payload.admission_id is not None:
        await _require_admission_scope(
            db,
            payload.admission_id,
            current_db_user.facility_id,
            patient_id=payload.patient_id,
        )
    if payload.encounter_id is not None:
        await _require_encounter_scope(
            db,
            payload.encounter_id,
            payload.patient_id,
            current_db_user.facility_id,
        )
    endpoint = "POST /nursing/vitals"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return VitalsOut.model_validate(cached.response_body)
    vitals = await service.record_vitals(db, payload, recorded_by=current_db_user.id)
    response = VitalsOut.model_validate(vitals)
    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            http_status.HTTP_201_CREATED,
            response.model_dump(mode="json"),
            current_db_user.id,
        )
    return response


@router.get(
    "/patients/{patient_id}/vitals",
    response_model=list[VitalsOut],
    dependencies=[Depends(require_roles(*_READ_ROLES))],
)
async def get_patient_vitals(
    patient_id: UUID,
    current_db_user: CurrentDbUser,
    since: datetime | None = Query(default=None, description="Inclusive lower bound on measured_at."),
    until: datetime | None = Query(default=None, description="Inclusive upper bound on measured_at."),
    db: AsyncSession = Depends(get_db),
) -> list[VitalsOut]:
    """Time-series for #193's chart, oldest first.

    Spans OPD and IPD: vitals hang off an encounter or an admission, and a
    patient who was seen then admitted has both. Filtering by one would drop
    half the trend.
    """
    await _require_patient_scope(db, patient_id, current_db_user.facility_id)
    rows = await service.list_vitals(db, patient_id, since=since, until=until)
    return [VitalsOut.model_validate(r) for r in rows]


@router.post(
    "/medication-administrations",
    response_model=MedicationAdministrationOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("nurse", "admin"))],
)
async def create_medication_administration(
    payload: MedicationAdministrationCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> MedicationAdministrationOut:
    """Record what happened to one prescribed dose: given, held or refused.

    Restricted to nurses: administration is theirs to record, and the eMAR is
    read in an adverse-event review as a statement of who did what.
    """
    await _require_patient_scope(db, payload.patient_id, current_db_user.facility_id)
    await _require_admission_scope(
        db,
        payload.admission_id,
        current_db_user.facility_id,
        patient_id=payload.patient_id,
    )
    await _require_prescription_item_for_patient(
        db,
        payload.prescription_item_id,
        payload.patient_id,
        current_db_user.facility_id,
    )
    record = await service.record_administration(db, payload, recorded_by=current_db_user.id)
    return MedicationAdministrationOut.model_validate(record)


@router.get(
    "/admissions/{admission_id}/medication-administrations",
    response_model=list[MedicationAdministrationOut],
    dependencies=[Depends(require_roles(*_READ_ROLES))],
)
async def get_admission_emar(
    admission_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> list[MedicationAdministrationOut]:
    await _require_admission_scope(db, admission_id, current_db_user.facility_id)
    rows = await service.list_administrations(db, admission_id)
    return [MedicationAdministrationOut.model_validate(r) for r in rows]


@router.post(
    "/intake-output",
    response_model=IntakeOutputOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_RECORD_ROLES))],
)
async def create_intake_output(
    payload: IntakeOutputCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> IntakeOutputOut:
    await _require_admission_scope(db, payload.admission_id, current_db_user.facility_id)
    record = await service.record_intake_output(db, payload, recorded_by=current_db_user.id)
    return IntakeOutputOut.model_validate(record)


@router.get(
    "/admissions/{admission_id}/fluid-balance",
    response_model=FluidBalanceOut,
    dependencies=[Depends(require_roles(*_READ_ROLES))],
)
async def get_fluid_balance(
    admission_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> FluidBalanceOut:
    await _require_admission_scope(db, admission_id, current_db_user.facility_id)
    return FluidBalanceOut(**await service.fluid_balance(db, admission_id))


# ============================================================ nurse task queue (#210)

@router.get(
    "/tasks",
    response_model=list[OrderTaskOut],
    dependencies=[Depends(require_roles(*_READ_ROLES))],
)
async def list_pending_tasks(
    current_db_user: CurrentDbUser,
    patient_id: UUID | None = Query(default=None),
    order_type: str | None = Query(default=None, description="lab | radiology | procedure | ..."),
    db: AsyncSession = Depends(get_db),
) -> list[OrderTaskOut]:
    """Doctor's orders still outstanding, oldest first.

    Outstanding is placed / accepted / in_progress. Cancelled orders are not
    tasks; completed ones carry their check-off evidence.
    """
    if patient_id is not None:
        await _require_patient_scope(db, patient_id, current_db_user.facility_id)
    rows = await service.pending_orders(
        db,
        facility_id=current_db_user.facility_id,
        patient_id=patient_id,
        order_type=order_type,
    )
    return [OrderTaskOut.model_validate(r) for r in rows]


@router.post(
    "/tasks/{order_id}/accept",
    response_model=OrderTaskOut,
    dependencies=[Depends(require_roles(*_RECORD_ROLES))],
)
async def accept_task(
    order_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OrderTaskOut:
    """Take ownership. Idempotent — re-accepting keeps the first acceptance,
    because that is the one that says when the ward picked the order up."""
    await _require_order_scope(db, order_id, current_db_user.facility_id)
    try:
        order = await service.accept_order(db, order_id, accepted_by=current_db_user.id)
    except service.OrderNotFound:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "order_not_found")
    return OrderTaskOut.model_validate(order)


@router.post(
    "/tasks/{order_id}/complete",
    response_model=OrderTaskOut,
    dependencies=[Depends(require_roles(*_RECORD_ROLES))],
)
async def complete_task(
    order_id: UUID,
    payload: OrderCompleteRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> OrderTaskOut:
    """Check off an order: who, when, and optionally a note.

    Refuses a second check-off with 409. Overwriting the first timestamp and
    actor would destroy the only record that matters in a dispute about when
    something was actually done.
    """
    await _require_order_scope(db, order_id, current_db_user.facility_id)
    try:
        order = await service.complete_order(
            db, order_id, completed_by=current_db_user.id, note=payload.note)
    except service.OrderNotFound:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "order_not_found")
    except service.OrderAlreadyCompleted as exc:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail={"code": "already_completed",
                    "message": f"order was completed at {exc.completed_at.isoformat()}"},
        ) from exc
    return OrderTaskOut.model_validate(order)


# ============================================================ incident register (#236)

@router.post(
    "/incidents",
    response_model=IncidentOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_RECORD_ROLES))],
)
async def report_incident(
    payload: IncidentReport,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    """File a clinical incident (NABH DHS).

    Distinct from the DPDP/CERT-In data-breach path in 0022a — a patient fall
    and a leaked record have different reporters, reviewers and statutory
    clocks.
    """
    incident = await incidents.report_incident(
        db,
        facility_id=current_db_user.facility_id,
        reported_by=current_db_user.id,
        **payload.model_dump(exclude_none=False),
    )
    return IncidentOut.model_validate(incident)


@router.get(
    "/incidents",
    response_model=list[IncidentOut],
    dependencies=[Depends(require_roles("nurse", "doctor", "hod", "admin", "auditor"))],
)
async def list_incidents(
    current_db_user: CurrentDbUser,
    status: str | None = Query(default=None),
    patient_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentOut]:
    rows = await incidents.list_incidents(
        db, current_db_user.facility_id, status=status, patient_id=patient_id)
    return [IncidentOut.model_validate(r) for r in rows]


@router.patch(
    "/incidents/{incident_id}/review",
    response_model=IncidentOut,
    dependencies=[Depends(require_roles("hod", "admin"))],
)
async def review_incident(
    incident_id: UUID,
    payload: IncidentReviewRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> IncidentOut:
    """Advance an incident through review. There is no DELETE — an incident
    register that can be emptied is not a register."""
    try:
        incident = await incidents.review_incident(
            db, incident_id,
            status=payload.status,
            reviewed_by=current_db_user.id,
            root_cause=payload.root_cause,
            corrective_action=payload.corrective_action,
            caller_facility_id=current_db_user.facility_id,
        )
    except incidents.IncidentNotFound:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "incident_not_found")
    except incidents.IncidentClosureIncomplete as exc:
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "closure_incomplete", "message": str(exc)},
        ) from exc
    return IncidentOut.model_validate(incident)
