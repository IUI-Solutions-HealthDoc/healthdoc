"""Facility pulse capture and the control-room board.

The capture reads clinical tables once per facility every 15 minutes and keeps
only counts. The board reads the latest capture per facility inside the
caller's scope; it never touches clinical tables, so an officer refreshing the
board costs nothing at the hospitals.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Bed, Ward
from app.common.patient_scope import facility_timezone
from app.departments.models import Department
from app.inventory.models import InventoryBatch, InventoryItem, StockLocation
from app.monitor.models import FacilityPulse, MonitorScope
from app.opd.models import Visit
from app.orders.models import Order
from app.pathology.models import LabOrderItem
from app.queue.models import QueueToken, Roster
from app.users.models import Facility


def utcnow() -> datetime:
    """The board's clock; tests pin it."""
    return datetime.now(UTC)


CAPTURE_INTERVAL = timedelta(minutes=15)
#: Three missed captures before a facility reads as not reporting.
STALE_AFTER = timedelta(minutes=45)
EXPIRY_HORIZON_DAYS = 30

_ED_CLOSED = ("completed", "cancelled", "lwbs", "closed")
_LAB_OPEN = ("placed", "accepted", "in_progress")

# Status thresholds, shown on the board so a red is never unexplained.
BED_RED, BED_AMBER = 90, 75
STOCK_RED = 5


async def capture_facility(db: AsyncSession, facility: Facility, *, now: datetime) -> FacilityPulse:
    """Count one facility's live state. Counts only; no patient identifiers."""
    tz = await facility_timezone(db, facility.id)
    local_today = now.astimezone(tz).date()
    day_start = datetime.combine(local_today, time.min, tzinfo=tz).astimezone(UTC)

    async def count(stmt) -> int:
        return int((await db.execute(stmt)).scalar_one() or 0)

    opd_today = await count(
        select(func.count(Visit.id)).where(
            Visit.facility_id == facility.id, Visit.visit_type == "opd", Visit.visit_date >= day_start
        )
    )
    queue_waiting = await count(
        select(func.count(QueueToken.id)).where(
            QueueToken.facility_id == facility.id,
            QueueToken.status == "waiting",
            QueueToken.created_at >= day_start,
        )
    )
    emergency_open = await count(
        select(func.count(Visit.id)).where(
            Visit.facility_id == facility.id,
            Visit.visit_type == "emergency",
            Visit.status.not_in(_ED_CLOSED),
        )
    )
    # Occupancy from admissions: beds.status is a mirror and drifts.
    admitted_now = await count(
        select(func.count(Admission.id))
        .join(Ward, Ward.id == Admission.ward_id)
        .where(Ward.facility_id == facility.id, Admission.status == "admitted")
    )
    beds_total = await count(
        select(func.count(Bed.id))
        .join(Ward, Ward.id == Bed.ward_id)
        .where(Ward.facility_id == facility.id, Ward.is_active.is_(True), Bed.status != "maintenance")
    )
    lab_pending = await count(
        select(func.count(LabOrderItem.id))
        .join(Order, Order.id == LabOrderItem.order_id)
        .where(Order.facility_id == facility.id, LabOrderItem.status.in_(_LAB_OPEN))
    )
    # An expired batch is stock nobody can dispense, so it does not count.
    usable = case(
        (InventoryBatch.expiry_date >= local_today, InventoryBatch.quantity - InventoryBatch.reserved_quantity),
        else_=0,
    )
    on_hand = (
        select(InventoryBatch.item_id.label("item_id"), func.sum(usable).label("available"))
        .join(StockLocation, StockLocation.id == InventoryBatch.stock_location_id)
        .where(StockLocation.facility_id == facility.id)
        .group_by(InventoryBatch.item_id)
        .subquery()
    )
    stock_below_reorder = await count(
        select(func.count())
        .select_from(on_hand)
        .join(InventoryItem, InventoryItem.id == on_hand.c.item_id)
        .where(
            InventoryItem.is_active.is_(True),
            InventoryItem.reorder_level > 0,
            on_hand.c.available < InventoryItem.reorder_level,
        )
    )
    batches_expiring_30d = await count(
        select(func.count(InventoryBatch.id))
        .join(StockLocation, StockLocation.id == InventoryBatch.stock_location_id)
        .where(
            StockLocation.facility_id == facility.id,
            InventoryBatch.quantity > 0,
            InventoryBatch.expiry_date >= local_today,
            InventoryBatch.expiry_date <= local_today + timedelta(days=EXPIRY_HORIZON_DAYS),
        )
    )
    staff_rostered_today = await count(
        select(func.count(func.distinct(Roster.staff_user_id)))
        .join(Department, Department.id == Roster.department_id)
        .where(
            Department.facility_id == facility.id,
            Roster.roster_date == local_today,
            Roster.is_available.is_(True),
        )
    )
    pulse = FacilityPulse(
        id=uuid.uuid4(),
        facility_id=facility.id,
        captured_at=now,
        opd_today=opd_today,
        queue_waiting=queue_waiting,
        emergency_open=emergency_open,
        admitted_now=admitted_now,
        beds_total=beds_total,
        lab_pending=lab_pending,
        stock_below_reorder=stock_below_reorder,
        batches_expiring_30d=batches_expiring_30d,
        staff_rostered_today=staff_rostered_today,
    )
    db.add(pulse)
    return pulse


async def capture_all(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Capture every active facility. One facility's failure does not stop the rest."""
    now = now or datetime.now(UTC)
    facilities = (
        await db.execute(select(Facility).where(Facility.is_active.is_(True)).order_by(Facility.code))
    ).scalars().all()
    captured = 0
    for facility in facilities:
        await capture_facility(db, facility, now=now)
        await db.flush()
        captured += 1
    return captured


# ------------------------------------------------------------------ the board


@dataclass(frozen=True)
class Area:
    state_code: str
    district: str | None


async def scope_for(db: AsyncSession, keycloak_sub: str) -> list[Area]:
    rows = (
        await db.execute(select(MonitorScope).where(MonitorScope.keycloak_sub == keycloak_sub))
    ).scalars().all()
    return [Area(row.state_code, row.district) for row in rows]


def _in_scope(areas: list[Area]):
    """Facilities inside any granted area. District names compare case-blind."""
    return or_(
        *(
            and_(
                Facility.state_code == area.state_code,
                func.lower(func.trim(Facility.district)) == area.district.strip().lower(),
            )
            if area.district is not None
            else Facility.state_code == area.state_code
            for area in areas
        )
    )


def status_of(pulse: FacilityPulse | None, *, now: datetime) -> tuple[str, list[str]]:
    """Red / amber / green / grey with the reasons, so a colour is never unexplained."""
    if pulse is None or now - pulse.captured_at > STALE_AFTER:
        return "grey", ["not reporting"]
    rank = {"green": 0, "amber": 1, "red": 2}
    level = "green"
    reasons: list[str] = []

    def flag(colour: str, reason: str) -> None:
        nonlocal level
        if rank[colour] > rank[level]:
            level = colour
        reasons.append(reason)

    occupancy = occupancy_percent(pulse)
    if occupancy is not None and occupancy >= BED_AMBER:
        flag("red" if occupancy >= BED_RED else "amber", f"beds {occupancy}% full")
    if pulse.stock_below_reorder:
        flag(
            "red" if pulse.stock_below_reorder >= STOCK_RED else "amber",
            f"{pulse.stock_below_reorder} medicines below reorder level",
        )
    if pulse.staff_rostered_today == 0 and pulse.opd_today > 0:
        flag("amber", "patients seen but no staff on today's roster")
    return level, reasons


def occupancy_percent(pulse: FacilityPulse) -> int | None:
    if pulse.beds_total <= 0:
        return None
    return round(100 * pulse.admitted_now / pulse.beds_total)


async def board(
    db: AsyncSession, areas: list[Area], *, now: datetime | None = None
) -> list[tuple[Facility, FacilityPulse | None]]:
    """Latest capture per in-scope facility; a facility never captured has None."""
    now = now or utcnow()
    if not areas:
        return []
    facility_filter = [Facility.is_active.is_(True), _in_scope(areas)]
    latest = (
        select(FacilityPulse.facility_id, func.max(FacilityPulse.captured_at).label("at"))
        .where(FacilityPulse.captured_at >= now - timedelta(days=1))
        .group_by(FacilityPulse.facility_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Facility, FacilityPulse)
            .outerjoin(latest, latest.c.facility_id == Facility.id)
            .outerjoin(
                FacilityPulse,
                and_(FacilityPulse.facility_id == Facility.id, FacilityPulse.captured_at == latest.c.at),
            )
            .where(*facility_filter)
            .order_by(Facility.district, Facility.name)
        )
    ).all()
    return [(facility, pulse) for facility, pulse in rows]
