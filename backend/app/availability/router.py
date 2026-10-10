"""Public bed and blood availability, no login (the /availability page).

Built from the control room's 15-minute captures, for facilities whose owner
has turned publish_availability on. Counts only: free beds per ward and units
of blood per group that could be issued now. Nothing here names a patient or a
member of staff, and nothing reads a clinical table on request, so a busy
public page costs the hospitals nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import get_db
from app.monitor import service as monitor
from app.monitor.models import FacilityPulse
from app.users.models import Facility

router = APIRouter(prefix="/public", tags=["public"])

#: A state's listing is bounded; a public endpoint must not return the world.
FACILITY_LIMIT = 300


class WardAvailability(BaseModel):
    ward: str
    free: int
    beds: int


class FacilityAvailability(BaseModel):
    facility_id: uuid.UUID
    name: str
    district: str | None
    facility_type: str | None
    updated_at: datetime | None
    #: True when the last capture is older than the control room's not-reporting window.
    stale: bool
    beds_free: int | None
    beds_total: int | None
    wards: list[WardAvailability]
    blood: dict[str, int]


class AvailabilityOut(BaseModel):
    state_code: str
    district: str | None
    generated_at: datetime
    facilities: list[FacilityAvailability]
    note: str = (
        "Counts are updated every 15 minutes and may have changed. Call the hospital before travelling."
    )


@router.get("/availability", response_model=AvailabilityOut)
async def public_availability(
    db: AsyncSession = Depends(get_db),
    state: str = Query(min_length=2, max_length=5, pattern=r"^[A-Za-z]{2,5}$"),
    district: str | None = Query(None, max_length=100),
) -> AvailabilityOut:
    now = monitor.utcnow()
    state_code = state.upper()
    latest = (
        select(FacilityPulse.facility_id, func.max(FacilityPulse.captured_at).label("at"))
        .where(FacilityPulse.captured_at >= now - timedelta(days=1))
        .group_by(FacilityPulse.facility_id)
        .subquery()
    )
    filters = [Facility.is_active.is_(True), Facility.publish_availability.is_(True), Facility.state_code == state_code]
    if district:
        filters.append(func.lower(func.trim(Facility.district)) == district.strip().lower())
    rows = (
        await db.execute(
            select(Facility, FacilityPulse)
            .outerjoin(latest, latest.c.facility_id == Facility.id)
            .outerjoin(
                FacilityPulse,
                and_(FacilityPulse.facility_id == Facility.id, FacilityPulse.captured_at == latest.c.at),
            )
            .where(*filters)
            .order_by(Facility.district, Facility.name)
            .limit(FACILITY_LIMIT)
        )
    ).all()
    out = []
    for facility, pulse in rows:
        detail = (pulse.detail or {}) if pulse is not None else {}
        wards = [
            WardAvailability(ward=w["ward"], free=w["free"], beds=w["beds"]) for w in detail.get("wards", [])
        ]
        out.append(
            FacilityAvailability(
                facility_id=facility.id,
                name=facility.name,
                district=facility.district,
                facility_type=facility.facility_type,
                updated_at=pulse.captured_at if pulse is not None else None,
                stale=pulse is None or now - pulse.captured_at > monitor.STALE_AFTER,
                beds_free=max(pulse.beds_total - pulse.admitted_now, 0) if pulse is not None else None,
                beds_total=pulse.beds_total if pulse is not None else None,
                wards=wards,
                blood=detail.get("blood", {}),
            )
        )
    return AvailabilityOut(state_code=state_code, district=district, generated_at=now, facilities=out)
