from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.common.modules import require_module
from app.common.redis import stock_alert_channel, subscribe
from app.pharmacy.schemas import (
    DispenseCreate,
    DispenseItemOut,
    DispenseOut,
    ExpiryTrackerResponse,
    MedicineSearchResponse,
    PrescriptionQueueResponse,
    SubstitutionApprovalRequest,
)
from app.pharmacy.service import (
    approve_substitution,
    create_dispense,
    get_expiry_tracker,
    get_prescription_queue,
    search_medicines,
)

_CREATE_DISPENSE_ENDPOINT = "POST /pharmacy/dispenses"

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/ping")
async def ping() -> dict:
    return {"module": "pharmacy", "status": "ok"}


@router.get(
    "/queue",
    response_model=PrescriptionQueueResponse,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def prescription_queue(
    current_user: CurrentDbUser,
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
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin", "doctor")),
    ],
)
async def medicine_search(
    current_user: CurrentDbUser,
    db: DbSession,
    q: str = Query(min_length=1),
) -> MedicineSearchResponse:
    results = await search_medicines(db, q=q, facility_id=current_user.facility_id)
    return MedicineSearchResponse(items=results)


@router.get(
    "/expiry-tracker",
    response_model=ExpiryTrackerResponse,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def expiry_tracker_endpoint(
    current_user: CurrentDbUser,
    db: DbSession,
    stock_location_id: UUID | None = None,
    threshold_days: int = Query(default=30, ge=1),
) -> ExpiryTrackerResponse:
    return await get_expiry_tracker(
        db,
        facility_id=current_user.facility_id,
        stock_location_id=stock_location_id,
        threshold_days=threshold_days,
    )


@router.get(
    "/stock-alerts",
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def stock_alerts_sse(
    current_user: CurrentDbUser,
):
    async def event_generator():
        async with subscribe(stock_alert_channel(current_user.facility_id)) as pubsub:
            async for message in pubsub.listen():
                if message and message.get("type") == "message":
                    data = message.get("data")
                    yield f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/dispenses",
    response_model=DispenseOut,
    status_code=201,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist")),
    ],
)
async def create_dispense_endpoint(
    payload: DispenseCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> DispenseOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")

    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _CREATE_DISPENSE_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body

    result = await create_dispense(
        db,
        payload,
        current_user_id=current_user.id,
        facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _CREATE_DISPENSE_ENDPOINT, 201, response_body, current_user.id
    )
    return result

@router.post(
    "/dispenses/items/{item_id}/approve",
    response_model=DispenseItemOut,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("doctor")),
    ],
)
async def approve_substitution_endpoint(
    item_id: UUID,
    payload: SubstitutionApprovalRequest,
    current_user: CurrentDbUser,
    db: DbSession,
) -> DispenseItemOut:
    return await approve_substitution(
        db,
        payload,
        item_row_id=item_id,
        approving_user_id=current_user.id,
        facility_id=current_user.facility_id,
    )


