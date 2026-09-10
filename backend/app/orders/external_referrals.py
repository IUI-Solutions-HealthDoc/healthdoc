"""Read-only referral inbox, independent of an open encounter or OPD token."""

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Encounter, Visit
from app.orders.models import Order, OrderExternalResult
from app.orders.schemas import ExternalReferralListOut, ExternalReferralOut, OrderOut
from app.patients.models import Patient

ReferralState = Literal["pending", "completed", "cancelled", "all"]


async def list_external_referrals(
    db: AsyncSession,
    *,
    caller_id: UUID,
    facility_id: UUID,
    caller_roles: list[str],
    state: ReferralState,
    limit: int,
    offset: int,
) -> ExternalReferralListOut:
    # Match the local results worklist scope. No caller-supplied doctor/facility
    # override. Constrain joins as well as the header so inconsistent legacy
    # foreign keys cannot disclose another facility/patient's visit.
    scope = [Order.facility_id == facility_id, Order.fulfilment_mode == "external_referral"]
    if "admin" not in caller_roles:
        scope.append(Order.created_by == caller_id)
    if state == "pending":
        scope.append(Order.status.notin_(["completed", "cancelled"]))
    elif state != "all":
        scope.append(Order.status == state)
    base = (
        select(Order)
        .join(Patient, (Patient.id == Order.patient_id) & (Patient.facility_id == facility_id))
        .join(
            Encounter, (Encounter.id == Order.encounter_id) & (Encounter.facility_id == facility_id)
        )
        .join(
            Visit,
            (Visit.id == Encounter.visit_id)
            & (Visit.facility_id == facility_id)
            & (Visit.patient_id == Order.patient_id),
        )
        .where(*scope)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    result_count = (
        select(func.count(OrderExternalResult.id))
        .where(OrderExternalResult.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    last_received = (
        select(func.max(OrderExternalResult.recorded_at))
        .where(OrderExternalResult.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            base.add_columns(
                Patient.full_name,
                func.coalesce(Patient.uhid, Patient.thid),
                Visit.visit_number,
                result_count,
                last_received,
            )
            .order_by(Order.ordered_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ExternalReferralListOut(
        items=[
            ExternalReferralOut(
                **OrderOut.model_validate(order).model_dump(),
                patient_name=name,
                patient_identifier=identifier,
                visit_number=visit_number,
                result_count=count,
                last_received_at=received,
            )
            for order, name, identifier, visit_number, count, received in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
