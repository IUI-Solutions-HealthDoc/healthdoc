"""Nursing service — vitals, eMAR, fluid balance (#390).

BMI and WHR are computed here and never accepted from the client. A derived
value a caller can set is a derived value that can disagree with its inputs,
and a wrong BMI in a chart is read as a measurement rather than as arithmetic.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import MedicationAdministrationStatus
from app.nursing.models import (
    IntakeOutputRecord,
    MedicationAdministration,
    NursingHandoverNote,
    Vitals,
)
from app.orders.models import PrescriptionItem
from app.users.models import User
from app.nursing.schemas import (
    HandoverNoteCreate,
    IntakeOutputCreate, MedicationAdministrationCreate, VitalsCreate,
)


class AdmissionNotFound(Exception):
    def __init__(self, admission_id: uuid.UUID) -> None:
        self.admission_id = admission_id


def _bmi(height_cm: Decimal | None, weight_kg: Decimal | None) -> Decimal | None:
    """kg / m². None unless both inputs are present and height is non-zero."""
    if height_cm is None or weight_kg is None or Decimal(height_cm) == 0:
        return None
    metres = Decimal(height_cm) / Decimal(100)
    return (Decimal(weight_kg) / (metres * metres)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _whr(waist_cm: Decimal | None, hip_cm: Decimal | None) -> Decimal | None:
    if waist_cm is None or hip_cm is None or Decimal(hip_cm) == 0:
        return None
    return (Decimal(waist_cm) / Decimal(hip_cm)).quantize(Decimal("0.01"), ROUND_HALF_UP)


async def record_vitals(
    db: AsyncSession, payload: VitalsCreate, *, recorded_by: uuid.UUID
) -> Vitals:
    """One measurement set, against an encounter (OPD) or an admission (IPD).

    `measured_at` defaults to now but may be backdated — a paper observation
    transcribed an hour later must keep the time it was actually taken, or the
    chart in #193 draws the wrong line.
    """
    vitals = Vitals(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        encounter_id=payload.encounter_id,
        admission_id=payload.admission_id,
        measured_at=payload.measured_at or datetime.now(timezone.utc),
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        bmi=_bmi(payload.height_cm, payload.weight_kg),
        waist_cm=payload.waist_cm,
        hip_cm=payload.hip_cm,
        whr=_whr(payload.waist_cm, payload.hip_cm),
        temp_c=payload.temp_c,
        pulse_bpm=payload.pulse_bpm,
        resp_rate=payload.resp_rate,
        bp_systolic=payload.bp_systolic,
        bp_diastolic=payload.bp_diastolic,
        spo2_pct=payload.spo2_pct,
        pain_score=payload.pain_score,
        created_by=recorded_by,
    )
    db.add(vitals)
    await db.flush()
    await db.refresh(vitals)
    return vitals


async def list_vitals(
    db: AsyncSession,
    patient_id: uuid.UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Vitals]:
    """The time-series behind #193's chart.

    Filtered by patient, NOT by encounter or admission: a patient seen in OPD
    and later admitted has vitals hanging off both, and a chart that showed only
    one side would silently drop half the trend at the moment it matters most.

    Ordered oldest-first — that is the order a chart plots in, and it saves the
    caller reversing it.
    """
    stmt = select(Vitals).where(Vitals.patient_id == patient_id)
    if since is not None:
        stmt = stmt.where(Vitals.measured_at >= since)
    if until is not None:
        stmt = stmt.where(Vitals.measured_at <= until)
    rows = await db.execute(stmt.order_by(Vitals.measured_at.asc()))
    return list(rows.scalars().all())


async def record_administration(
    db: AsyncSession, payload: MedicationAdministrationCreate, *, recorded_by: uuid.UUID
) -> MedicationAdministration:
    """One eMAR entry. `held` and `refused` carry a reason; the schema and the
    0043 CHECK both enforce it, deliberately — the API should reject it with a
    422 that names the field, and the database should still refuse if anything
    ever writes around the API."""
    record = MedicationAdministration(
        id=uuid.uuid4(),
        prescription_item_id=payload.prescription_item_id,
        admission_id=payload.admission_id,
        patient_id=payload.patient_id,
        scheduled_at=payload.scheduled_at,
        administered_at=payload.administered_at or datetime.now(timezone.utc),
        status=payload.status,
        dose_given=payload.dose_given,
        reason=payload.reason,
        notes=payload.notes,
        created_by=recorded_by,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    # So the 201 body has the same shape as the list rows — a client should not
    # have to know that one carries the drug name and the other does not.
    return await _attach_medicine(db, record)


async def _attach_medicine(db: AsyncSession, record: MedicationAdministration) -> MedicationAdministration:
    """Copy the prescribed drug name, dose and route onto one record.

    Same reason as the join in list_administrations: a caller holding only
    prescription_item_id cannot say what was given.
    """
    item = await db.get(PrescriptionItem, record.prescription_item_id)
    record.medicine_name = item.medicine_name if item else None
    record.dosage = item.dosage if item else None
    record.route = item.route if item else None
    return record


async def list_administrations(
    db: AsyncSession, admission_id: uuid.UUID
) -> list[MedicationAdministration]:
    """The ward eMAR table for one admission, most recent first.

    Joined to prescription_items for the drug name, prescribed dose and route.
    Without them the response carries only prescription_item_id, and an eMAR
    that cannot say which drug a dose was is not an eMAR — the screen would
    have to fetch every item separately, one request per row.

    LEFT join, not inner: a dose that was actually given must never disappear
    from the record because its prescription item did. The name renders as
    unknown; the administration stays.

    `dosage` (what was prescribed) and `dose_given` (what the nurse recorded)
    are deliberately both present. They are the same number most of the time,
    and the times they are not are the ones worth seeing.
    """
    rows = await db.execute(
        select(
            MedicationAdministration,
            PrescriptionItem.medicine_name,
            PrescriptionItem.dosage,
            PrescriptionItem.route,
        )
        .outerjoin(
            PrescriptionItem,
            PrescriptionItem.id == MedicationAdministration.prescription_item_id,
        )
        .where(MedicationAdministration.admission_id == admission_id)
        .order_by(MedicationAdministration.administered_at.desc())
    )

    records: list[MedicationAdministration] = []
    for record, medicine_name, dosage, route in rows.all():
        record.medicine_name = medicine_name
        record.dosage = dosage
        record.route = route
        records.append(record)
    return records


async def record_intake_output(
    db: AsyncSession, payload: IntakeOutputCreate, *, recorded_by: uuid.UUID
) -> IntakeOutputRecord:
    record = IntakeOutputRecord(
        id=uuid.uuid4(),
        admission_id=payload.admission_id,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
        entry_type=payload.entry_type,
        volume_ml=payload.volume_ml,
        notes=payload.notes,
        created_by=recorded_by,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def fluid_balance(db: AsyncSession, admission_id: uuid.UUID) -> dict:
    """Running intake/output totals for one admission.

    Direction comes from the entry_type prefix, not from the sign of volume_ml,
    which 0023's CHECK keeps positive. That is why a new IntakeOutputType value
    must keep the intake_/output_ prefix convention — anything else silently
    lands in neither total.
    """
    rows = await db.execute(
        select(IntakeOutputRecord.entry_type, IntakeOutputRecord.volume_ml)
        .where(IntakeOutputRecord.admission_id == admission_id)
    )
    intake = output = 0
    for entry_type, volume_ml in rows.all():
        if entry_type.startswith("intake_"):
            intake += volume_ml
        elif entry_type.startswith("output_"):
            output += volume_ml
    return {
        "admission_id": admission_id,
        "total_intake_ml": intake,
        "total_output_ml": output,
        "net_ml": intake - output,
    }


#: Re-exported so callers can compare without importing the enum module.
GIVEN = MedicationAdministrationStatus.GIVEN.value


# ============================================================ order check-off (#210)
#
# The nurse task queue. Uses orders.status plus 0045's accepted/completed
# evidence columns rather than a parallel nursing_tasks table: a nurse checking
# off a doctor's order is the same state transition a lab tech performs when
# accepting a sample, and two tables answering "what is outstanding?" would
# disagree the first time an order completed through the other path.

from app.common.enums import OrderStatus  # noqa: E402
from app.orders.models import Order  # noqa: E402


class OrderNotFound(Exception):
    def __init__(self, order_id: uuid.UUID) -> None:
        self.order_id = order_id


class OrderAlreadyCompleted(Exception):
    """Re-completing would overwrite who checked it off, and when."""

    def __init__(self, order_id: uuid.UUID, completed_at) -> None:
        self.order_id = order_id
        self.completed_at = completed_at


async def pending_orders(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    order_type: str | None = None,
) -> list[Order]:
    """Everything still outstanding — the queue in #210.

    'Outstanding' is placed / accepted / in_progress. Cancelled orders are not
    tasks, and completed ones have their evidence recorded.
    """
    open_statuses = (
        OrderStatus.PLACED.value,
        OrderStatus.ACCEPTED.value,
        OrderStatus.IN_PROGRESS.value,
    )
    stmt = select(Order).where(Order.status.in_(open_statuses))
    if facility_id is not None:
        stmt = stmt.where(Order.facility_id == facility_id)
    if patient_id is not None:
        stmt = stmt.where(Order.patient_id == patient_id)
    if order_type is not None:
        stmt = stmt.where(Order.order_type == order_type)
    rows = await db.execute(stmt.order_by(Order.ordered_at.asc()))
    return list(rows.scalars().all())


async def accept_order(
    db: AsyncSession, order_id: uuid.UUID, *, accepted_by: uuid.UUID
) -> Order:
    """Take ownership of an order. Idempotent: re-accepting keeps the first
    acceptance, because the first is the one that says when the ward picked
    it up."""
    order = await db.get(Order, order_id)
    if order is None:
        raise OrderNotFound(order_id)

    if order.accepted_at is None:
        order.accepted_at = datetime.now(timezone.utc)
        order.accepted_by = accepted_by
        if order.status == OrderStatus.PLACED.value:
            order.status = OrderStatus.ACCEPTED.value
        await db.flush()
        await db.refresh(order)
    return order


async def complete_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    *,
    completed_by: uuid.UUID,
    note: str | None = None,
) -> Order:
    """Check off an order: who, when, and optionally why it went the way it did.

    Refuses to re-complete. A second check-off would overwrite the first
    timestamp and actor, and in a dispute about when something was given, the
    original entry is the only one that matters.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise OrderNotFound(order_id)
    if order.completed_at is not None:
        raise OrderAlreadyCompleted(order_id, order.completed_at)

    now = datetime.now(timezone.utc)
    # A directly-completed order was implicitly accepted at the same moment;
    # leaving accepted_at NULL would lose that it was ever picked up.
    if order.accepted_at is None:
        order.accepted_at = now
        order.accepted_by = completed_by
    order.completed_at = now
    order.completed_by = completed_by
    order.completion_note = note
    order.status = OrderStatus.COMPLETED.value

    await db.flush()
    await db.refresh(order)
    return order


async def record_handover_note(
    db: AsyncSession,
    payload: HandoverNoteCreate,
    *,
    recorded_by: uuid.UUID,
    facility_id: uuid.UUID,
) -> NursingHandoverNote:
    """Record one SBAR shift handover.

    The receiving nurse is validated here rather than trusted from the body:
    an id that is inactive, belongs to another facility or does not exist would
    otherwise be stored as the person who accepted responsibility for a
    patient, and the handover would name somebody who never took it.

    Handing over to yourself is refused. It is the one case that looks like a
    handover in every report and transfers nothing.
    """
    if payload.handed_over_to == recorded_by:
        raise HTTPException(
            422, "A handover must name a different nurse as the receiver."
        )

    # Through the ORM rather than raw SQL: `users.id` is a UUID column, and a
    # textual comparison against it binds a string on SQLite and silently
    # matches nothing — the same shape as the fixture trap in CLAUDE.md.
    receiver = (
        await db.execute(
            select(User.id).where(
                User.id == payload.handed_over_to,
                User.facility_id == facility_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    # 404, not 403: a 403 would confirm the user exists at another facility.
    if receiver is None:
        raise HTTPException(404, "Receiving nurse not found")

    note = NursingHandoverNote(
        id=uuid.uuid4(),
        admission_id=payload.admission_id,
        shift=payload.shift.value,
        situation=payload.situation,
        background=payload.background,
        assessment=payload.assessment,
        recommendation=payload.recommendation,
        handed_over_to=payload.handed_over_to,
        created_by=recorded_by,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


async def list_handover_notes(
    db: AsyncSession, admission_id: uuid.UUID
) -> list[dict]:
    """Handovers for one admission, most recent first.

    Names are resolved in the same query. The ward board renders a list of
    these, and a per-row user fetch is the N+1 that makes a screen a nurse
    refreshes constantly feel broken.
    """
    receiver = aliased(User)
    author = aliased(User)
    rows = (
        await db.execute(
            select(
                NursingHandoverNote,
                receiver.full_name.label("handed_over_to_name"),
                author.full_name.label("created_by_name"),
            )
            .outerjoin(receiver, receiver.id == NursingHandoverNote.handed_over_to)
            .outerjoin(author, author.id == NursingHandoverNote.created_by)
            .where(NursingHandoverNote.admission_id == admission_id)
            .order_by(NursingHandoverNote.created_at.desc())
        )
    ).all()
    return [
        {
            "id": note.id,
            "admission_id": note.admission_id,
            "shift": note.shift,
            "situation": note.situation,
            "background": note.background,
            "assessment": note.assessment,
            "recommendation": note.recommendation,
            "handed_over_to": note.handed_over_to,
            "handed_over_to_name": receiver_name,
            "created_by": note.created_by,
            "created_by_name": author_name,
            "created_at": note.created_at,
        }
        for note, receiver_name, author_name in rows
    ]


async def list_handover_candidates(
    db: AsyncSession, *, facility_id: uuid.UUID, exclude_user_id: uuid.UUID,
    search: str | None = None,
) -> list[User]:
    """Colleagues this nurse can hand over to.

    Facility-scoped, active-only and self-excluding, because each of those is a
    rule record_handover_note already enforces — a picker that offers a name the
    write path will refuse is worse than an empty one.

    Not filtered to users who hold `nurse`: roles live in Keycloak, not in
    `users`, so answering that here would mean an Admin API round trip per
    keystroke. The write path stays the enforcement point.
    """
    statement = select(User).where(
        User.facility_id == facility_id,
        User.id != exclude_user_id,
        User.is_active.is_(True),
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(User.full_name.ilike(term), User.username.ilike(term))
        )
    statement = statement.order_by(User.full_name).limit(10)
    return list((await db.execute(statement)).scalars().all())
