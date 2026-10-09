"""Control room for state and district officers (realm role `monitor`).

Like platform, this uses the JWT identity: an officer belongs to no hospital,
so has no users row. What the officer may see is the area granted in
monitor_scopes; with none, the board is refused rather than shown empty, so a
missing grant is never mistaken for a quiet district.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, require_roles
from app.common.db import get_db
from app.monitor import service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["monitor"], dependencies=[Depends(require_roles("monitor"))])


class AreaOut(BaseModel):
    state_code: str
    district: str | None


class ThresholdsOut(BaseModel):
    bed_red_percent: int = service.BED_RED
    bed_amber_percent: int = service.BED_AMBER
    stock_red_items: int = service.STOCK_RED
    not_reporting_after_minutes: int = int(service.STALE_AFTER.total_seconds() // 60)


class FacilityRowOut(BaseModel):
    facility_id: uuid.UUID
    code: str
    name: str
    district: str | None
    facility_type: str | None
    status: str
    reasons: list[str]
    captured_at: datetime | None
    opd_today: int | None
    queue_waiting: int | None
    emergency_open: int | None
    admitted_now: int | None
    beds_total: int | None
    bed_occupancy_percent: int | None
    lab_pending: int | None
    stock_below_reorder: int | None
    batches_expiring_30d: int | None
    staff_rostered_today: int | None
    equipment_down: int | None
    critical_equipment_down: int | None


class TotalsOut(BaseModel):
    facilities: int
    reporting: int
    red: int
    amber: int
    green: int
    grey: int
    opd_today: int
    emergency_open: int
    admitted_now: int
    beds_total: int
    stock_below_reorder: int
    equipment_down: int


class BoardOut(BaseModel):
    areas: list[AreaOut]
    districts: list[str]
    generated_at: datetime
    thresholds: ThresholdsOut
    totals: TotalsOut
    facilities: list[FacilityRowOut]


def _row(facility, pulse, *, now: datetime) -> FacilityRowOut:
    status, reasons = service.status_of(pulse, now=now)
    counts = {
        name: getattr(pulse, name) if pulse is not None else None
        for name in (
            "opd_today", "queue_waiting", "emergency_open", "admitted_now", "beds_total",
            "lab_pending", "stock_below_reorder", "batches_expiring_30d", "staff_rostered_today",
            "equipment_down", "critical_equipment_down",
        )
    }
    return FacilityRowOut(
        facility_id=facility.id,
        code=facility.code,
        name=facility.name,
        district=facility.district,
        facility_type=facility.facility_type,
        status=status,
        reasons=reasons,
        captured_at=pulse.captured_at if pulse is not None else None,
        bed_occupancy_percent=service.occupancy_percent(pulse) if pulse is not None else None,
        **counts,
    )


@router.get("/board", response_model=BoardOut)
async def get_board(
    user: AuthUser = Depends(require_roles("monitor")),
    db: AsyncSession = Depends(get_db),
    district: str | None = Query(None, max_length=100),
) -> BoardOut:
    areas = await service.scope_for(db, user.sub)
    if not areas:
        raise HTTPException(
            403,
            {"code": "monitor_scope_missing", "message": "No state or district has been granted to this account."},
        )
    now = service.utcnow()
    everything = await service.board(db, areas, now=now)
    shown = (
        [(f, p) for f, p in everything if (f.district or "").strip().lower() == district.strip().lower()]
        if district
        else everything
    )
    rows = [_row(f, p, now=now) for f, p in shown]
    # Who looked at what, without any patient data: the board holds none.
    log.info(
        "monitor board read",
        extra={"monitor_sub": user.sub, "district": district, "facilities": len(rows)},
    )
    reporting = [r for r in rows if r.status != "grey"]
    return BoardOut(
        areas=[AreaOut(state_code=a.state_code, district=a.district) for a in areas],
        districts=sorted({(f.district or "").strip() for f, _ in everything if f.district}),
        generated_at=now,
        thresholds=ThresholdsOut(),
        totals=TotalsOut(
            facilities=len(rows),
            reporting=len(reporting),
            red=sum(r.status == "red" for r in rows),
            amber=sum(r.status == "amber" for r in rows),
            green=sum(r.status == "green" for r in rows),
            grey=sum(r.status == "grey" for r in rows),
            opd_today=sum(r.opd_today or 0 for r in reporting),
            emergency_open=sum(r.emergency_open or 0 for r in reporting),
            admitted_now=sum(r.admitted_now or 0 for r in reporting),
            beds_total=sum(r.beds_total or 0 for r in reporting),
            stock_below_reorder=sum(r.stock_below_reorder or 0 for r in reporting),
            equipment_down=sum(r.equipment_down or 0 for r in reporting),
        ),
        facilities=rows,
    )


class WardOut(BaseModel):
    ward: str
    department: str | None
    beds: int
    occupied: int
    free: int
    maintenance: int


class StockShortOut(BaseModel):
    item: str
    strength: str | None
    available: str
    reorder_level: str


class ExpiringOut(BaseModel):
    item: str
    batch: str
    expiry: str
    quantity: str


class StaffOut(BaseModel):
    name: str
    designation: str | None
    department: str | None
    shift: str | None
    active_today: bool
    waiting: int


class EquipmentDownOut(BaseModel):
    name: str
    category: str
    location: str | None
    critical: bool
    status: str
    since: str
    reason: str | None


class FacilityDetailOut(BaseModel):
    facility: FacilityRowOut
    equipment: list[EquipmentDownOut]
    staff: list[StaffOut]
    wards: list[WardOut]
    stock_short: list[StockShortOut]
    expiring: list[ExpiringOut]
    list_limit: int = service.DETAIL_LIMIT


@router.get("/facilities/{facility_id}", response_model=FacilityDetailOut)
async def get_facility_detail(
    facility_id: uuid.UUID,
    user: AuthUser = Depends(require_roles("monitor")),
    db: AsyncSession = Depends(get_db),
) -> FacilityDetailOut:
    found = await service.facility_in_scope(db, await service.scope_for(db, user.sub), facility_id)
    if found is None:
        raise HTTPException(404, {"code": "facility_not_found", "message": "Facility not found"})
    facility, pulse = found
    now = service.utcnow()
    detail = pulse.detail if pulse is not None and service.status_of(pulse, now=now)[0] != "grey" else {}
    log.info("monitor facility read", extra={"monitor_sub": user.sub, "facility_id": str(facility.id)})
    return FacilityDetailOut(
        facility=_row(facility, pulse, now=now),
        equipment=detail.get("equipment", []),
        staff=detail.get("staff", []),
        wards=detail.get("wards", []),
        stock_short=detail.get("stock_short", []),
        expiring=detail.get("expiring", []),
    )


class TrendOut(BaseModel):
    district: str | None
    icd_version: str
    icd_code: str
    title: str | None
    #: A number, or "<5" when fewer patients than that: never a small exact count.
    this_week: str
    last_week: str
    spike: bool


class TrendsOut(BaseModel):
    week_ending: str
    small_cell_below: int = service.SMALL_CELL
    spike_rule: str = f"this week ≥ {service.SPIKE_RATIO}× last week and ≥ {service.SPIKE_MIN} patients"
    trends: list[TrendOut]


def _cell(n: int) -> str:
    return f"<{service.SMALL_CELL}" if 0 < n < service.SMALL_CELL else str(n)


@router.get("/trends", response_model=TrendsOut)
async def get_disease_trends(
    user: AuthUser = Depends(require_roles("monitor")),
    db: AsyncSession = Depends(get_db),
    district: str | None = Query(None, max_length=100),
) -> TrendsOut:
    areas = await service.scope_for(db, user.sub)
    if not areas:
        raise HTTPException(
            403,
            {"code": "monitor_scope_missing", "message": "No state or district has been granted to this account."},
        )
    # Weeks are reckoned in IST, the business day every HealthDoc facility uses.
    today = service.utcnow().astimezone(service.IST).date()
    trends = await service.disease_trends(db, areas, today=today, district=district)
    log.info("monitor trends read", extra={"monitor_sub": user.sub, "district": district})
    return TrendsOut(
        week_ending=today.isoformat(),
        trends=[
            TrendOut(
                district=t.district, icd_version=t.icd_version, icd_code=t.icd_code, title=t.title,
                this_week=_cell(t.this_week), last_week=_cell(t.last_week),
                # A spike is only flagged on a count large enough to show.
                spike=t.spike,
            )
            for t in trends
        ],
    )
