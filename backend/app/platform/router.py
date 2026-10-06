"""Platform-safe workspace for the cloud-only superadmin role.

This router deliberately uses the JWT identity rather than CurrentDbUser. A
platform operator does not belong to a hospital, so requiring a users row with
a facility_id is both inaccurate and the reason the role previously had no
usable workspace. Only facility metadata is returned; there are no patient,
encounter, identity-merge or clinical joins here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, require_roles
from app.common.db import get_db
from app.platform import onboarding
from app.users.models import Facility, User
from app.users.schemas import StaffUsername
from app.users.service import KeycloakAdmin

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
    name_hi: str | None = None
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


# =============================================================================
# Onboarding a facility (platform/onboarding.py)
# =============================================================================

class PlatformFacilityCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    state_code: str = Field(min_length=2, max_length=5)
    timezone: str = "Asia/Kolkata"
    district: str | None = Field(default=None, max_length=100)
    ownership: Literal["government", "private"] | None = None
    hfr_facility_id: str | None = None


class PlatformFacilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    district: str | None = Field(default=None, max_length=100)
    ownership: Literal["government", "private"] | None = None
    hfr_facility_id: str | None = None
    is_active: bool | None = None


class PlatformAdminCreate(BaseModel):
    username: StaffUsername
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    temporary_password: str = Field(min_length=8, repr=False)


class PlatformCopySetup(BaseModel):
    source_facility_id: uuid.UUID


def _refused(exc: onboarding.OnboardingError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


async def _facility(db: AsyncSession, facility_id: uuid.UUID) -> Facility:
    facility = await db.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(404, {"code": "facility_not_found", "message": "Facility not found"})
    return facility


@router.post("/facilities", status_code=201, response_model=PlatformFacilityOut)
async def create_platform_facility(
    payload: PlatformFacilityCreate, db: AsyncSession = Depends(get_db)
) -> PlatformFacilityOut:
    try:
        facility = await onboarding.create_facility(db, **payload.model_dump())
    except onboarding.OnboardingError as exc:
        raise _refused(exc) from exc
    return PlatformFacilityOut.model_validate(facility)


@router.patch("/facilities/{facility_id}", response_model=PlatformFacilityOut)
async def update_platform_facility(
    facility_id: uuid.UUID, payload: PlatformFacilityUpdate, db: AsyncSession = Depends(get_db)
) -> PlatformFacilityOut:
    facility = await _facility(db, facility_id)
    try:
        await onboarding.update_facility(db, facility, payload.model_dump(exclude_unset=True))
    except onboarding.OnboardingError as exc:
        raise _refused(exc) from exc
    return PlatformFacilityOut.model_validate(facility)


@router.post("/facilities/{facility_id}/admins", status_code=201)
async def create_platform_facility_admin(
    facility_id: uuid.UUID, payload: PlatformAdminCreate, db: AsyncSession = Depends(get_db)
) -> dict:
    """The facility's first admin. Keycloak first (the identity source of
    truth, as in users/router.create_user), then the users row there."""
    facility = await _facility(db, facility_id)
    if not facility.is_active:
        raise HTTPException(409, {"code": "facility_inactive", "message": "This facility is inactive"})
    if (await db.execute(select(User.id).where(User.username == payload.username))).first() is not None:
        raise HTTPException(409, {"code": "username_in_use", "message": f"Username '{payload.username}' already exists"})
    sub = await KeycloakAdmin().create_user(
        username=payload.username, full_name=payload.full_name, email=payload.email,
        temporary_password=payload.temporary_password, roles=["admin"],
    )
    user = User(
        keycloak_sub=sub, username=payload.username, full_name=payload.full_name, email=payload.email,
        facility_id=facility.id, is_active=True,
    )
    db.add(user)
    await db.flush()
    return {"id": str(user.id), "username": user.username, "facility_id": str(facility.id), "roles": ["admin"]}


@router.post("/facilities/{facility_id}/copy-setup")
async def copy_platform_facility_setup(
    facility_id: uuid.UUID, payload: PlatformCopySetup, db: AsyncSession = Depends(get_db)
) -> dict:
    target = await _facility(db, facility_id)
    source = await _facility(db, payload.source_facility_id)
    author = await onboarding.earliest_staff(db, target.id)
    if author is None:
        raise HTTPException(409, {"code": "no_admin", "message": "Create the facility's admin first: the tariff names who set it"})
    try:
        counts = await onboarding.copy_setup(
            db, source=source, target=target, author_id=author.id,
            today=datetime.now(ZoneInfo(target.timezone)).date(),
        )
    except onboarding.OnboardingError as exc:
        raise _refused(exc) from exc
    return {"facility_id": str(target.id), "copied_from": str(source.id), **counts}
