"""wards module router — endpoints land here; see this module's GitHub issues."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.admissions import service
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.wards.schemas import BedGridItemOut, BedGridOut, BedOccupantOut

router = APIRouter(prefix="/wards", tags=["wards"])


_WARD_ROLES = ("doctor", "nurse", "admin")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "wards", "status": "ok"}


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
