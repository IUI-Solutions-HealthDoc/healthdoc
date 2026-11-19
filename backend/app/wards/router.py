"""wards module router — endpoints land here; see this module's GitHub issues."""
import uuid

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions import service
from app.admissions.models import Admission, Bed, Ward
from app.audit.actions import AuditAction
from app.audit.service import write_audit_log
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.wards.schemas import (
    BedGridItemOut,
    BedGridOut,
    BedMismatchOut,
    BedOccupantOut,
    BedReconciliationOut,
    WardOut,
)

router = APIRouter(prefix="/wards", tags=["wards"])


_WARD_ROLES = ("doctor", "nurse", "admin")


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "wards", "status": "ok"}


@router.get(
    "",
    response_model=list[WardOut],
    dependencies=[Depends(require_roles(*_WARD_ROLES))],
)
async def list_wards(
    current_db_user: CurrentDbUser,
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[WardOut]:
    query = select(Ward).where(Ward.facility_id == current_db_user.facility_id)
    if active_only:
        query = query.where(Ward.is_active.is_(True))
    query = query.order_by(Ward.name)
    rows = (await db.execute(query)).scalars().all()
    return [WardOut.model_validate(row) for row in rows]


@router.get(
    "/beds/reconciliation",
    response_model=BedReconciliationOut,
    dependencies=[Depends(require_roles("admin"))],
)
async def get_bed_reconciliation(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> BedReconciliationOut:
    """Where beds.status and the admissions table disagree, for this facility.

    Declared before /{ward_id}/beds on purpose: FastAPI matches in declaration
    order, and although "beds" would fail UUID parsing today, a future change
    to a string ward key would silently shadow this route.

    Always scoped to the caller's facility. reconcile_bed_status() accepts
    facility_id=None for a full cross-facility sweep, but that stays available
    to the maintenance job only — an HTTP surface that returns another
    facility's bed board is a tenancy leak, not an admin convenience.
    """
    mismatches = await service.reconcile_bed_status(db, current_db_user.facility_id)
    return BedReconciliationOut(
        facility_id=current_db_user.facility_id,
        mismatch_count=len(mismatches),
        mismatches=[BedMismatchOut(**m) for m in mismatches],
    )


@router.get(
    "/{ward_id}/beds",
    response_model=BedGridOut,
    dependencies=[Depends(require_roles(*_WARD_ROLES))],
)
async def get_ward_bed_grid(
    ward_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> BedGridOut:
    try:
        grid = await service.get_ward_bed_grid(db, ward_id, current_db_user.facility_id)
    except service.WardNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ward not found")

    return BedGridOut(
        ward_id=ward_id,
        items=[
            BedGridItemOut(
                bed_id=item["bed_id"],
                bed_number=item["bed_number"],
                status=item["status"],
                occupant=BedOccupantOut(**item["occupant"]) if item["occupant"] else None,
            )
            for item in grid
        ],
    )


# ---------------------------------------------------------------- bed management
#
# Nothing created beds: a new facility's wards had none, so nobody could be
# admitted until someone wrote SQL (QA 10 Oct 2026). Beds are added and taken
# out of service, never deleted; admissions reference them for ever.


class BedCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    bed_number: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ./-]*$")


class BedStatusChange(BaseModel):
    status: Literal["vacant", "maintenance"]
    reason: str = Field(min_length=3, max_length=300)


class BedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ward_id: uuid.UUID
    bed_number: str
    status: str


async def _scoped_ward(db: AsyncSession, ward_id: uuid.UUID, facility_id: uuid.UUID) -> Ward:
    ward = await db.get(Ward, ward_id)
    if ward is None or ward.facility_id != facility_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ward not found")
    return ward


@router.post(
    "/{ward_id}/beds",
    response_model=BedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin"))],
)
async def add_bed(
    ward_id: uuid.UUID, payload: BedCreate, current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> BedOut:
    """Idempotent by bed number: the same number in the same ward is the same bed."""
    await _scoped_ward(db, ward_id, current_db_user.facility_id)
    number = " ".join(payload.bed_number.split()).upper()
    existing = (await db.execute(
        select(Bed).where(Bed.ward_id == ward_id, Bed.bed_number == number)
    )).scalar_one_or_none()
    if existing is not None:
        return BedOut.model_validate(existing)
    bed = Bed(id=uuid.uuid4(), ward_id=ward_id, bed_number=number, status="vacant")
    db.add(bed)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "bed_number_taken",
                            "message": f"Bed {number} already exists in this ward"}) from None
    await write_audit_log(
        db, facility_id=current_db_user.facility_id, action=AuditAction.CREATE, resource_type="beds",
        user_id=current_db_user.id, resource_id=bed.id, new_value={"ward_id": str(ward_id), "bed_number": number},
    )
    return BedOut.model_validate(bed)


@router.patch(
    "/beds/{bed_id}",
    response_model=BedOut,
    dependencies=[Depends(require_roles("admin"))],
)
async def change_bed_status(
    bed_id: uuid.UUID, payload: BedStatusChange, current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> BedOut:
    """Take a bed out of service (maintenance) or bring it back (vacant).

    Occupancy is the admission's, not this endpoint's: a bed with an active
    admission cannot be changed here (beds.status mirrors admissions).
    """
    bed = (await db.execute(select(Bed).where(Bed.id == bed_id).with_for_update())).scalar_one_or_none()
    if bed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bed not found")
    await _scoped_ward(db, bed.ward_id, current_db_user.facility_id)
    occupied = (await db.execute(
        select(Admission.id).where(Admission.bed_id == bed.id, Admission.status == "admitted").limit(1)
    )).scalar_one_or_none()
    if occupied is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "bed_occupied",
                            "message": "A patient is admitted to this bed. Transfer or discharge them first."})
    if bed.status not in ("vacant", "maintenance"):
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "bed_not_changeable",
                            "message": f"A {bed.status} bed cannot be changed here"})
    before = bed.status
    bed.status = payload.status
    await db.flush()
    await write_audit_log(
        db, facility_id=current_db_user.facility_id, action=AuditAction.UPDATE, resource_type="beds",
        user_id=current_db_user.id, resource_id=bed.id, old_value={"status": before},
        new_value={"status": bed.status}, reason=payload.reason.strip(),
    )
    return BedOut.model_validate(bed)
