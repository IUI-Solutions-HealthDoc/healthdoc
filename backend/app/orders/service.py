"""backend/app/orders/service.py -- order creation. Allocates a gapless
order_number (ORD-<YYYYMMDD>-<SEQ6>) the same way opd/service.py does
for visit_number. facility_id is denormalized from the encounter,
same reasoning as app/encounters/service.py (required for audit
auto-logging, safer than trusting client input)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies.interactions import check_interactions
from app.allergies.service import AllergyConflict, check_prescription_item
from app.audit.service import write_audit_log
from app.common.enums import FulfilmentMode, OrderStatus
from app.common.facility_modules import FacilityModule
from app.files.models import FileRecord
from app.inventory.models import InventoryItem
from app.opd.models import Encounter, Visit
from app.opd.service import _business_date
from app.orders import order_number
from app.orders.models import Order, OrderExternalResult, Prescription, PrescriptionItem
from app.orders.schemas import ExternalResultCreate, OrderCreate, PrescriptionCreate
from app.users.models import Facility


class EncounterNotFound(Exception):
    def __init__(self, encounter_id: UUID):
        self.encounter_id = encounter_id


class PatientMismatch(Exception):
    def __init__(self, expected_patient_id: UUID):
        self.expected_patient_id = expected_patient_id


class ExternalResultOrderNotFound(Exception):
    pass


class ExternalResultConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class ExternalResultFileInvalid(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


#: Which optional module fulfils each order type (§2 v3.3, ModuleCode).
#:
#: `procedure` is absent ON PURPOSE and must stay absent. ProcedureSetting is
#: explicitly decoupled from the OT module so a minor procedure is recordable at
#: a facility with no theatre — mapping it to `ot` would make every OPD dressing
#: an external referral at such a facility.
_FULFILLING_MODULE = {
    "lab": "lab",
    "radiology": "radiology",
    "pharmacy": "pharmacy",
    "blood": "blood_bank",
}


async def _fulfilment_mode(db: AsyncSession, *, facility_id: uuid.UUID, order_type: str) -> str:
    """internal, or external_referral when the fulfilling module is switched off.

    §2 v3.3 rule 1: "Ordering never disappears. A doctor can always record what
    the patient needs — clinical completeness is not conditional on the hospital
    owning the equipment. The order is created with
    fulfilment_mode='external_referral' instead of being refused."

    That rule was documented and never implemented. POST /orders is not
    module-gated, so the order WAS created — but fulfilment_mode was never set
    by any code path, so it defaulted to 'internal'. A facility with lab
    disabled therefore recorded lab orders claiming the hospital would run them
    in-house, with no module to pick them up and no accession ever generated.
    Silently mislabelling a clinical instruction is worse than refusing it.

    Absent row means enabled — the same convention require_module() uses.
    Keeping both in one shape matters: if they ever disagreed, an order could be
    marked internal by one rule and refused by the other.

    Uses the mapped FacilityModule rather than raw text() SQL. A bare `:param`
    inside text() carries NO type information, so the value goes to the driver
    untouched: asyncpg accepts a UUID object, sqlite3 raises "type 'UUID' is not
    supported". A Core select against the mapped column lets SQLAlchemy bind it
    correctly on both, which is the only version of this that is right
    everywhere rather than right on the database you happened to test.
    """
    module_code = _FULFILLING_MODULE.get(order_type)
    if module_code is None:
        return "internal"

    row = await db.execute(
        select(FacilityModule.is_enabled).where(
            FacilityModule.facility_id == facility_id,
            FacilityModule.module_code == module_code,
        )
    )
    return "internal" if row.scalar_one_or_none() is not False else "external_referral"


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

    visit = await db.get(Visit, encounter.visit_id)
    if visit is None:
        raise EncounterNotFound(payload.encounter_id)
    if visit.patient_id != payload.patient_id:
        raise PatientMismatch(visit.patient_id)

    facility = await db.get(Facility, encounter.facility_id)
    business_date = _business_date(facility.timezone)
    seq = await order_number.next_order_sequence(db, encounter.facility_id, business_date)

    order = Order(
        id=uuid.uuid4(),
        # facility.code, not the caller's facility — same rule as facility_id
        # and the business date above: one facility in play, the resource's.
        order_number=order_number.format_order_number(facility.code, business_date, seq),
        encounter_id=payload.encounter_id,
        facility_id=encounter.facility_id,
        patient_id=visit.patient_id,
        order_type=payload.order_type,
        priority=payload.priority,
        status="placed",
        ordered_at=payload.ordered_at or datetime.now(UTC),
        created_by=payload.created_by,
        # The resource's facility, consistent with every other field here.
        fulfilment_mode=await _fulfilment_mode(
            db, facility_id=encounter.facility_id, order_type=payload.order_type
        ),
    )
    db.add(order)
    await db.flush()
    return order


async def get_order(db: AsyncSession, order_id: UUID) -> Order | None:
    result = await db.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()


async def list_orders_for_encounter(
    db: AsyncSession, encounter_id: UUID, facility_id: UUID
) -> list[Order]:
    result = await db.execute(
        select(Order)
        .where(Order.encounter_id == encounter_id, Order.facility_id == facility_id)
        .order_by(Order.ordered_at.desc(), Order.created_at.desc())
    )
    return list(result.scalars().all())


async def _external_result_order(
    db: AsyncSession, *, order_id: UUID, facility_id: UUID, lock: bool = False
) -> Order:
    statement = select(Order).where(
        Order.id == order_id,
        Order.facility_id == facility_id,
    )
    if lock:
        statement = statement.with_for_update()
    order = (await db.execute(statement)).scalar_one_or_none()
    if order is None:
        raise ExternalResultOrderNotFound
    return order


async def record_external_result(
    db: AsyncSession,
    *,
    order_id: UUID,
    payload: ExternalResultCreate,
    facility_id: UUID,
    recorded_by: UUID,
) -> OrderExternalResult:
    """Append an outside report and close the referred order on first receipt."""
    order = await _external_result_order(
        db, order_id=order_id, facility_id=facility_id, lock=True
    )
    if order.fulfilment_mode != FulfilmentMode.EXTERNAL_REFERRAL.value:
        raise ExternalResultConflict("order_not_external_referral")
    if order.status == OrderStatus.CANCELLED.value:
        raise ExternalResultConflict("order_cancelled")

    if payload.result_file_id is not None:
        file_record = await db.get(FileRecord, payload.result_file_id)
        if file_record is None or file_record.facility_id != facility_id:
            raise ExternalResultFileInvalid("result_file_not_found")
        if file_record.patient_id != order.patient_id:
            raise ExternalResultFileInvalid("result_file_not_for_order_patient")
        if file_record.is_erased:
            raise ExternalResultFileInvalid("result_file_erased")

    now = datetime.now(UTC)
    result = OrderExternalResult(
        id=uuid.uuid4(),
        order_id=order.id,
        provider_name=payload.provider_name,
        summary=payload.summary,
        result_file_id=payload.result_file_id,
        observed_on=payload.observed_on,
        recorded_by=recorded_by,
        recorded_at=now,
    )
    db.add(result)
    await db.flush()

    if order.completed_at is None:
        # Local import avoids a module cycle: nursing.service itself maps Order.
        from app.nursing.service import complete_order

        await complete_order(
            db,
            order.id,
            completed_by=recorded_by,
            note="External result recorded",
        )

    await write_audit_log(
        db,
        facility_id=facility_id,
        action="create",
        resource_type="order_external_results",
        resource_id=result.id,
        user_id=recorded_by,
        patient_id=order.patient_id,
        new_value={
            "order_id": str(order.id),
            "provider_name": payload.provider_name,
            "result_file_id": str(payload.result_file_id) if payload.result_file_id else None,
            "observed_on": payload.observed_on.isoformat() if payload.observed_on else None,
        },
    )
    await db.refresh(result)
    return result


async def list_external_results(
    db: AsyncSession, *, order_id: UUID, facility_id: UUID
) -> list[OrderExternalResult]:
    await _external_result_order(db, order_id=order_id, facility_id=facility_id)
    rows = await db.execute(
        select(OrderExternalResult)
        .where(OrderExternalResult.order_id == order_id)
        .order_by(
            OrderExternalResult.recorded_at.asc(),
            OrderExternalResult.created_at.asc(),
            OrderExternalResult.id.asc(),
        )
    )
    return list(rows.scalars().all())


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
    if encounter.ended_at is not None:
        from app.integrations.abdm.hip.publisher import publish_document

        await publish_document(db, kind="prescription", source_id=prescription.id,
                               visit=visit, actor_id=created_by)
    return prescription, warnings


async def get_prescription(
    db: AsyncSession,
    prescription_id: UUID,
    facility_id: UUID | None = None,
) -> Prescription | None:
    statement = select(Prescription).where(Prescription.id == prescription_id)
    if facility_id is not None:
        statement = statement.where(Prescription.facility_id == facility_id)
    result = await db.execute(statement)
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
