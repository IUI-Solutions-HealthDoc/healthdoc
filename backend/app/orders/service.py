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

from app.allergies.interactions import check_interactions
from app.allergies.service import AllergyConflict, check_prescription_item
from app.audit.service import write_audit_log
from app.inventory.models import InventoryItem
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


async def create_prescription(
    db: AsyncSession, payload: PrescriptionCreate, created_by: UUID,
) -> tuple[Prescription, list[str]]:
    """Prescription save with CDS checks wired in.

    Per item: resolve ingredient_code via medicine_item_id -> InventoryItem
    (no code if medicine_item_id is unset, e.g. a free-text drug not in
    the inventory catalog -- check_prescription_item() treats that as
    "unknown, cannot check", not "clear"). Then run the allergy check;
    AllergyConflict propagates to the caller (router maps it to a 409)
    UNLESS the item carries a valid override_reason, in which case the
    override is recorded on the row and a manual audit log is written
    for it -- PrescriptionItem has no facility_id of its own, so it
    can't use the __audit_resource_type__ auto-audit path (that
    requires the field directly on the model), same reason
    app.admissions.service writes admit/transfer audit logs by hand.

    Interaction checking runs once, across all items' resolved
    ingredient codes together, after every item has cleared (or been
    overridden past) its own allergy check. Returns the warning strings
    alongside the prescription rather than raising -- interactions never
    block a save (see app.allergies.interactions module docstring).
    """
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

    resolved_ingredient_codes: list[str | None] = []
    warnings: list[str] = []

    for item in payload.items:
        ingredient_code: str | None = None
        if item.medicine_item_id is not None:
            inventory_item = await db.get(InventoryItem, item.medicine_item_id)
            if inventory_item is not None:
                ingredient_code = inventory_item.ingredient_code
        resolved_ingredient_codes.append(ingredient_code)
        if ingredient_code is None:
            warnings.append(
                f"Allergy check not performed for '{item.medicine_name}' -- no ingredient code"
            )

        allergy_override_reason: str | None = None
        allergy_override_by: UUID | None = None

        try:
            matched = await check_prescription_item(
                db, patient_id=visit.patient_id, ingredient_code=ingredient_code,
                override_reason=item.override_reason,
            )
        except AllergyConflict:
            raise

        if matched is not None:
            # check_prescription_item only returns non-None when an
            # override was accepted (see its own docstring) -- record it.
            allergy_override_reason = item.override_reason
            allergy_override_by = created_by

        prescription_item = PrescriptionItem(
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
            allergy_override_reason=allergy_override_reason,
            allergy_override_by=allergy_override_by,
        )
        db.add(prescription_item)
        await db.flush()

        if matched is not None:
            await write_audit_log(
                db, facility_id=encounter.facility_id, action="allergy_override",
                resource_type="prescription_items", resource_id=prescription_item.id,
                user_id=created_by, patient_id=visit.patient_id, visit_id=visit.id,
                new_value={
                    "allergy_id": str(matched.id),
                    "substance": matched.substance_text,
                    "severity": matched.severity,
                    "override_reason": allergy_override_reason,
                },
            )

    interaction_warnings = check_interactions(resolved_ingredient_codes)
    warnings.extend(interaction_warnings)
    return prescription, warnings


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
