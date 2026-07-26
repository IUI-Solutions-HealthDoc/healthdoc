from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_roles
from app.common.db import get_db
from app.common.modules import require_module
from app.pharmacy.schemas import (
    DispenseCreate,
    DispenseOut,
    MedicineSearchResponse,
    PrescriptionQueueResponse,
)
from app.pharmacy.service import create_dispense, get_prescription_queue, search_medicines

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/ping")
async def ping() -> dict:
    return {"module": "pharmacy", "status": "ok"}


@router.get(
    "/queue",
    response_model=PrescriptionQueueResponse,
    dependencies=[Depends(require_module("pharmacy"))],
)
async def prescription_queue(
    current_user: Annotated[CurrentUser, Depends(require_roles("pharmacist", "admin"))],
    db: DbSession,
    department_id: UUID | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PrescriptionQueueResponse:
    return await get_prescription_queue(
        db,
        facility_id=current_user.facility_id,
        department_id=department_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/medicines/search",
    response_model=MedicineSearchResponse,
    dependencies=[Depends(require_module("pharmacy"))],
)
async def medicine_search(
    current_user: Annotated[CurrentUser, Depends(require_roles("pharmacist", "admin", "doctor"))],
    db: DbSession,
    q: str = Query(min_length=1),
) -> MedicineSearchResponse:
    results = await search_medicines(db, q=q, facility_id=current_user.facility_id)
    return MedicineSearchResponse(items=results)


@router.post(
    "/dispenses",
    response_model=DispenseOut,
    status_code=201,
    dependencies=[Depends(require_module("pharmacy"))],
)
async def create_dispense_endpoint(
    payload: DispenseCreate,
    current_user: Annotated[CurrentUser, Depends(require_roles("pharmacist"))],
    db: DbSession,
) -> DispenseOut:
    return await create_dispense(
        db,
        payload,
        current_user_id=current_user.id,
        facility_id=current_user.facility_id,
    )
