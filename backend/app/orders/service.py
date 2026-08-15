"""backend/app/orders/service.py -- order creation. Allocates a gapless
order_number (ORD-<YYYYMMDD>-<SEQ6>) the same way opd/service.py does
for visit_number. facility_id is denormalized from the encounter,
same reasoning as app/encounters/service.py (required for audit
auto-logging, safer than trusting client input)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Encounter
from app.opd.service import _business_date
from app.orders import order_number
from app.orders.models import Order
from app.orders.schemas import OrderCreate
from app.users.models import Facility


class EncounterNotFound(Exception):
    def __init__(self, encounter_id: UUID):
        self.encounter_id = encounter_id


async def create_order(db: AsyncSession, payload: OrderCreate) -> Order:
    """facility_timezone is no longer a caller-supplied parameter (see
    #362): it was previously resolved from current_db_user.facility_id
    in the router, which silently disagreed with encounter.facility_id
    -- the facility actually used for both Order.facility_id and the
    order_number_counters row -- on any cross-facility request. Timezone
    is now looked up from the encounter's OWN facility, right here,
    after the encounter is fetched, so there is exactly one facility in
    play for the whole function: the resource's, never the caller's."""
    result = await db.execute(select(Encounter).where(Encounter.id == payload.encounter_id))
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise EncounterNotFound(payload.encounter_id)

    facility = await db.get(Facility, encounter.facility_id)
    business_date = _business_date(facility.timezone)
    seq = await order_number.next_order_sequence(db, encounter.facility_id, business_date)

    order = Order(
        id=uuid.uuid4(),
        order_number=order_number.format_order_number(business_date, seq),
        encounter_id=payload.encounter_id,
        facility_id=encounter.facility_id,
        patient_id=payload.patient_id,
        order_type=payload.order_type,
        priority=payload.priority,
        status="placed",
        ordered_at=payload.ordered_at or datetime.now(timezone.utc),
        created_by=payload.created_by,
    )
    db.add(order)
    await db.flush()
    return order


async def get_order(db: AsyncSession, order_id: UUID) -> Order | None:
    result = await db.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()
