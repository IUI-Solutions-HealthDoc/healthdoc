"""wards module router — endpoints land here; see this module's GitHub issues."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions import service
from app.admissions.models import Ward
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
