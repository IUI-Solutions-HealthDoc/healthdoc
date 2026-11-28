"""Diet orders and meal records.

The rules that matter to a patient: one diet is in force at a time, a nil-by-
mouth patient is never recorded as having been served a meal, a meal is
recorded once, and a discharge stops the diet so the kitchen stops cooking for
an empty bed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Bed, Ward
from app.dietary.models import DietOrder, MealService
from app.opd.models import Visit
from app.patients.models import Patient

IST = ZoneInfo("Asia/Kolkata")


class DietError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def ward_today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


async def scoped_admission(
    db: AsyncSession, admission_id: uuid.UUID, facility_id: uuid.UUID, *, lock: bool = False,
) -> Admission:
    stmt = (
        select(Admission)
        .join(Visit, Visit.id == Admission.visit_id)
        .where(Admission.id == admission_id, Visit.facility_id == facility_id)
    )
    if lock:
        stmt = stmt.with_for_update(of=Admission)
    admission = (await db.execute(stmt)).scalar_one_or_none()
    if admission is None:
        # 404, never 403: another facility's admission does not exist for this caller.
        raise DietError("admission_not_found", "Admission not found", 404)
    return admission


async def active_order(db: AsyncSession, admission_id: uuid.UUID) -> DietOrder | None:
    return (
        await db.execute(
            select(DietOrder).where(DietOrder.admission_id == admission_id, DietOrder.status == "active")
        )
    ).scalar_one_or_none()


def _stop(order: DietOrder, *, user_id: uuid.UUID | None, reason: str, now: datetime) -> None:
    order.status, order.stopped_at, order.stopped_by, order.stop_reason = "stopped", now, user_id, reason


async def order_diet(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, admission_id: uuid.UUID,
    diet_type: str, instructions: str | None, food_allergies: str | None,
) -> DietOrder:
    admission = await scoped_admission(db, admission_id, facility_id, lock=True)
    if admission.status != "admitted":
        raise DietError("admission_not_active", "This patient is no longer admitted")
    instructions, food_allergies = _clean(instructions), _clean(food_allergies)
    if diet_type == "other" and instructions is None:
        raise DietError("instructions_required", "Say what the diet is: 'Other' tells the kitchen nothing", 422)
    now = datetime.now(UTC)
    current = await active_order(db, admission.id)
    if current is not None:
        if (current.diet_type, current.instructions, current.food_allergies) == (diet_type, instructions, food_allergies):
            raise DietError("diet_unchanged", "This diet is already in force")
        _stop(current, user_id=user_id, reason="Replaced by a new diet order", now=now)
        # Flush the stop before the insert: the partial unique index allows one
        # active order per admission and would refuse them in the other order.
        await db.flush()
    order = DietOrder(
        id=uuid.uuid4(), facility_id=facility_id, admission_id=admission.id, diet_type=diet_type,
        instructions=instructions, food_allergies=food_allergies, status="active", starts_at=now,
        ordered_by=user_id,
    )
    db.add(order)
    await db.flush()
    return order


async def stop_diet(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, order_id: uuid.UUID, reason: str,
) -> DietOrder:
    order = (
        await db.execute(
            select(DietOrder).where(DietOrder.id == order_id, DietOrder.facility_id == facility_id).with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise DietError("diet_order_not_found", "Diet order not found", 404)
    if order.status != "active":
        raise DietError("diet_order_stopped", "This diet order has already been stopped")
    reason = _clean(reason)
    if reason is None:
        raise DietError("reason_required", "Say why the diet is stopped", 422)
    _stop(order, user_id=user_id, reason=reason, now=datetime.now(UTC))
    await db.flush()
    return order


async def stop_for_discharge(db: AsyncSession, admission_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Called inside discharge_patient's transaction."""
    current = await active_order(db, admission_id)
    if current is not None:
        _stop(current, user_id=user_id, reason="Patient discharged", now=datetime.now(UTC))


async def record_meal(
    db: AsyncSession, *, facility_id: uuid.UUID, user_id: uuid.UUID, admission_id: uuid.UUID,
    service_date: date, meal: str, status: str, notes: str | None,
) -> MealService:
    admission = await scoped_admission(db, admission_id, facility_id, lock=True)
    if admission.status != "admitted":
        raise DietError("admission_not_active", "This patient is no longer admitted")
    today = ward_today()
    if service_date > today:
        raise DietError("meal_in_future", "A meal cannot be recorded for a day that has not come", 422)
    admitted_day = admission.admitted_at.replace(tzinfo=admission.admitted_at.tzinfo or UTC).astimezone(IST).date()
    if service_date < admitted_day:
        raise DietError("meal_before_admission", "That day is before this patient was admitted", 422)
    notes = _clean(notes)
    if status == "not_served" and notes is None:
        raise DietError("reason_required", "Say why the meal was not served", 422)
    order = await active_order(db, admission.id)
    if status == "served" and order is not None and order.diet_type == "npo":
        # The one record that must never read as routine.
        raise DietError("patient_is_npo", "This patient is nil by mouth. A meal cannot be recorded as served.")
    existing = (
        await db.execute(
            select(MealService.id).where(
                MealService.admission_id == admission.id, MealService.service_date == service_date,
                MealService.meal == meal,
            )
        )
    ).first()
    if existing is not None:
        raise DietError("meal_already_recorded", "This meal is already recorded for this patient today")
    record = MealService(
        id=uuid.uuid4(), facility_id=facility_id, admission_id=admission.id,
        diet_order_id=order.id if order else None, service_date=service_date, meal=meal, status=status,
        notes=notes, recorded_by=user_id, recorded_at=datetime.now(UTC),
    )
    db.add(record)
    await db.flush()
    return record


async def kitchen_board(
    db: AsyncSession, facility_id: uuid.UUID, service_date: date, ward_id: uuid.UUID | None = None,
) -> list[dict]:
    """Every patient admitted now, by ward and bed, with the diet in force and
    that day's meals. A patient with no diet order is listed too: 'no order'
    is what the kitchen must chase, not a row to hide."""
    stmt = (
        select(Admission, Ward.name, Bed.bed_number, Patient.full_name, Patient.uhid)
        .join(Visit, Visit.id == Admission.visit_id)
        .join(Ward, Ward.id == Admission.ward_id)
        .join(Bed, Bed.id == Admission.bed_id)
        .join(Patient, Patient.id == Admission.patient_id)
        .where(Visit.facility_id == facility_id, Admission.status == "admitted")
        .order_by(Ward.name, Bed.bed_number)
    )
    if ward_id is not None:
        stmt = stmt.where(Admission.ward_id == ward_id)
    rows = (await db.execute(stmt)).all()
    ids = [admission.id for admission, *_ in rows]
    orders = {
        o.admission_id: o
        for o in (
            await db.execute(select(DietOrder).where(DietOrder.admission_id.in_(ids), DietOrder.status == "active"))
        ).scalars()
    } if ids else {}
    meals: dict[uuid.UUID, list[MealService]] = {}
    if ids:
        for m in (
            await db.execute(
                select(MealService).where(MealService.admission_id.in_(ids), MealService.service_date == service_date)
            )
        ).scalars():
            meals.setdefault(m.admission_id, []).append(m)
    return [
        {
            "admission_id": admission.id,
            "ward_id": admission.ward_id,
            "ward_name": ward_name,
            "bed_number": bed_number,
            "patient_name": full_name,
            "uhid": uhid,
            "diet": orders.get(admission.id),
            "meals": meals.get(admission.id, []),
        }
        for admission, ward_name, bed_number, full_name, uhid in rows
    ]
