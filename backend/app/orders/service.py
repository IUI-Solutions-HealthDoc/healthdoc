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

from app.opd.models import Encounter, Visit
from app.opd.service import _business_date
from app.orders import order_number
from app.orders.models import Order, Prescription, PrescriptionItem
from app.orders.schemas import OrderCreate, PrescriptionCreate
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


async def create_prescription(db: AsyncSession, payload: PrescriptionCreate, created_by: UUID) -> Prescription:
    """Plain prescription save -- no CDS check yet (allergy/interaction
    wiring lands in a follow-up PR stacked on this one). Encounter has
    no patient_id of its own (only visit_id), so patient_id is resolved
    via encounter -> visit, same two-hop pattern the schema doc's ER
    diagram implies for every other encounter-scoped write."""
    result = await db.execute(select(Encounter).where(Encounter.id == payload.encounter_id))
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise EncounterNotFound(payload.encounter_id)

    visit = await db.get(Visit, encounter.visit_id)
    if visit is None:
        raise EncounterNotFound(payload.encounter_id)

    prescription = Prescription(
        id=uuid.uuid4(),
        encounter_id=payload.encounter_id,
        facility_id=encounter.facility_id,
        patient_id=visit.patient_id,
        notes=payload.notes,
        created_by=created_by,
    )
    db.add(prescription)
    await db.flush()

    for item in payload.items:
        db.add(PrescriptionItem(
            id=uuid.uuid4(),
            prescription_id=prescription.id,
            medicine_item_id=item.medicine_item_id,
            medicine_name=item.medicine_name,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            route=item.route,
            instructions=item.instructions,
            status="prescribed",
        ))
    await db.flush()
    return prescription


async def get_prescription(db: AsyncSession, prescription_id: UUID) -> Prescription | None:
    result = await db.execute(select(Prescription).where(Prescription.id == prescription_id))
    return result.scalar_one_or_none()


async def get_prescription_items(db: AsyncSession, prescription_id: UUID) -> list[PrescriptionItem]:
    """No relationship() is declared on Prescription/PrescriptionItem in
    this module (both are plain Column-only models), so items are
    fetched as a separate query rather than via ORM-relationship
    loading -- callers that need a full PrescriptionOut (header +
    items) must call this alongside get_prescription()/create_prescription()."""
    result = await db.execute(
        select(PrescriptionItem)
        .where(PrescriptionItem.prescription_id == prescription_id)
        .order_by(PrescriptionItem.created_at.asc())
    )
    return list(result.scalars().all())
