"""Platform-safe workspace for the cloud-only superadmin role.

This router deliberately uses the JWT identity rather than CurrentDbUser. A
platform operator does not belong to a hospital, so requiring a users row with
a facility_id is both inaccurate and the reason the role previously had no
usable workspace. Only facility metadata is returned; there are no patient,
encounter, identity-merge or clinical joins here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, require_roles
from app.common.db import get_db
from app.users.models import Facility

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(require_roles("superadmin"))],
)


class PlatformFacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    state_code: str
    district: str | None
    facility_type: str | None
    hfr_facility_id: str | None
    timezone: str
    is_active: bool


class PlatformFacilityListOut(BaseModel):
    items: list[PlatformFacilityOut]
    total: int
    page: int
    page_size: int


@router.get("/facilities", response_model=PlatformFacilityListOut)
async def list_platform_facilities(
    _user: AuthUser = Depends(require_roles("superadmin")),
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PlatformFacilityListOut:
    filters = []
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Facility.name.ilike(term),
                Facility.code.ilike(term),
                Facility.hfr_facility_id.ilike(term),
            )
        )

    query = select(Facility)
    count_query = select(func.count()).select_from(Facility)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    rows = (
        await db.execute(
            query.order_by(Facility.name.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    total = int((await db.execute(count_query)).scalar_one())
    return PlatformFacilityListOut(
        items=[PlatformFacilityOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
