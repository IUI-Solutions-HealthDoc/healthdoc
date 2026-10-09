"""A facility's day as a control-room officer may see it (slice 6).

Who was treated, what was given or done, and which staff did it, with the
patient as a masked reference instead of a name. The reference is an HMAC of
(facility, day, patient) under a key derived from the server's PII key: it is
the same for one patient all day, so an officer can follow one journey, and
different the next day and at another facility, so it does not become a
standing identifier. It cannot be reversed without the server key.

This reads clinical tables for one facility and one day, bounded, and every
read is written to that facility's audit log. Opening a named record is a
separate, break-glass action and is not offered here.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admissions.models import Admission, Discharge, Ward
from app.common.config import get_settings
from app.common.patient_scope import facility_timezone
from app.departments.models import Department
from app.opd.models import Encounter, Visit
from app.orders.models import Order, PrescriptionItem
from app.ot.models import OtRecord, OtSchedule
from app.pathology.models import LabOrderItem, LabResult
from app.pharmacy.models import PharmacyDispense, PharmacyDispenseItem
from app.users.models import User

#: A day with more events than this is shown truncated, and says so.
EVENT_LIMIT = 500
#: How far back an officer may look. Older days belong in reports, not the room.
MAX_DAYS_BACK = 90

_KEY_LABEL = b"healthdoc/monitor-activity/v1"


def _key() -> bytes:
    # Domain-separated from every other use of the PII key.
    return hmac.new(get_settings().pii_encryption_key.encode(), _KEY_LABEL, hashlib.sha256).digest()


def patient_ref(facility_id: uuid.UUID, day: date, patient_id: uuid.UUID) -> str:
    digest = hmac.new(_key(), f"{facility_id}:{day.isoformat()}:{patient_id}".encode(), hashlib.sha256)
    return "P-" + digest.hexdigest()[:6].upper()


@dataclass(frozen=True)
class Event:
    at: datetime
    kind: str
    patient: str
    detail: str
    staff: str | None


async def day_trail(db: AsyncSession, facility_id: uuid.UUID, day: date) -> tuple[list[Event], bool]:
    """Events for one facility-local day, oldest first, and whether truncated."""
    tz = await facility_timezone(db, facility_id)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    staff = aliased(User)
    ref = lambda patient_id: patient_ref(facility_id, day, patient_id)  # noqa: E731
    events: list[Event] = []

    async def collect(stmt, build) -> None:
        for row in (await db.execute(stmt.limit(EVENT_LIMIT + 1))).all():
            events.append(build(*row))

    await collect(
        select(Visit.visit_date, Visit.patient_id, Visit.visit_type, Department.name, staff.full_name)
        .outerjoin(Department, Department.id == Visit.department_id)
        .outerjoin(staff, staff.id == Visit.created_by)
        .where(Visit.facility_id == facility_id, Visit.visit_date >= start, Visit.visit_date < end),
        lambda at, pid, vtype, dept, who: Event(
            at, "registered", ref(pid), " · ".join(x for x in (vtype.upper(), dept) if x), who
        ),
    )
    await collect(
        select(Encounter.started_at, Visit.patient_id, Department.name, staff.full_name)
        .join(Visit, Visit.id == Encounter.visit_id)
        .outerjoin(Department, Department.id == Visit.department_id)
        .outerjoin(staff, staff.id == Encounter.provider_user_id)
        .where(Encounter.facility_id == facility_id, Encounter.started_at >= start, Encounter.started_at < end),
        lambda at, pid, dept, who: Event(at, "consultation", ref(pid), dept or "", who),
    )
    await collect(
        select(PharmacyDispense.created_at, Visit.patient_id, PrescriptionItem.medicine_name,
               PharmacyDispenseItem.quantity_dispensed, staff.full_name)
        .join(PharmacyDispenseItem, PharmacyDispenseItem.dispense_id == PharmacyDispense.id)
        .join(PrescriptionItem, PrescriptionItem.id == PharmacyDispenseItem.prescription_item_id)
        .join(Visit, Visit.id == PharmacyDispense.visit_id)
        .outerjoin(staff, staff.id == PharmacyDispense.dispensed_by)
        .where(Visit.facility_id == facility_id, PharmacyDispense.is_current.is_(True),
               PharmacyDispense.created_at >= start, PharmacyDispense.created_at < end),
        lambda at, pid, medicine, qty, who: Event(
            at, "medicine", ref(pid), f"{medicine} × {format(qty, 'f')}" if qty is not None else medicine, who
        ),
    )
    await collect(
        select(LabResult.created_at, Order.patient_id, LabOrderItem.test_name, LabResult.status, staff.full_name)
        .join(LabOrderItem, LabOrderItem.id == LabResult.lab_order_item_id)
        .join(Order, Order.id == LabOrderItem.order_id)
        .outerjoin(staff, staff.id == LabResult.created_by)
        .where(Order.facility_id == facility_id, LabResult.version == 1,
               LabResult.created_at >= start, LabResult.created_at < end),
        lambda at, pid, test, status, who: Event(at, "lab_result", ref(pid), f"{test} · {status}", who),
    )
    await collect(
        select(OtRecord.started_at, OtSchedule.patient_id, OtRecord.procedure_performed, OtSchedule.procedure_name,
               staff.full_name)
        .join(OtSchedule, OtSchedule.id == OtRecord.ot_schedule_id)
        .outerjoin(staff, staff.id == OtRecord.surgeon_user_id)
        .where(OtSchedule.facility_id == facility_id, OtRecord.started_at >= start, OtRecord.started_at < end),
        lambda at, pid, performed, planned, who: Event(at, "surgery", ref(pid), performed or planned, who),
    )
    await collect(
        select(Admission.admitted_at, Admission.patient_id, Ward.name, staff.full_name)
        .join(Ward, Ward.id == Admission.ward_id)
        .outerjoin(staff, staff.id == Admission.created_by)
        .where(Ward.facility_id == facility_id, Admission.admitted_at >= start, Admission.admitted_at < end),
        lambda at, pid, ward, who: Event(at, "admitted", ref(pid), ward, who),
    )
    await collect(
        select(Discharge.discharged_at, Admission.patient_id, Discharge.discharge_type, staff.full_name)
        .join(Admission, Admission.id == Discharge.admission_id)
        .join(Ward, Ward.id == Admission.ward_id)
        .outerjoin(staff, staff.id == Discharge.created_by)
        .where(Ward.facility_id == facility_id, Discharge.discharged_at >= start, Discharge.discharged_at < end),
        lambda at, pid, kind, who: Event(at, "discharged", ref(pid), kind, who),
    )
    events.sort(key=lambda event: event.at)
    return events[:EVENT_LIMIT], len(events) > EVENT_LIMIT
