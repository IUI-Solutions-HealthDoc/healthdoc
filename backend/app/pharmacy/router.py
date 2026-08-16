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
    GrnCreate,
    GrnOut,
    GrnVerifyRequest,
    IndentCreate,
    IndentOut,
    IndentApprovalRequest,
    ReorderAlertsResponse,
    AdjustmentCreate,
    AdjustmentOut,
    AdjustmentApprovalRequest,
)
from app.pharmacy.service import (
    approve_substitution,
    create_dispense,
    get_expiry_tracker,
    get_prescription_queue,
    search_medicines,
    create_grn,
    verify_grn,
    create_indent,
    approve_indent,
    issue_indent,
    get_reorder_alerts,
    create_adjustment,
    approve_adjustment,
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



_CREATE_GRN_ENDPOINT = "POST /pharmacy/grn"
_VERIFY_GRN_ENDPOINT = "POST /pharmacy/grn/{grn_id}/verify"
_CREATE_INDENT_ENDPOINT = "POST /pharmacy/indents"
_APPROVE_INDENT_ENDPOINT = "POST /pharmacy/indents/{indent_id}/approve"
_ISSUE_INDENT_ENDPOINT = "POST /pharmacy/indents/{indent_id}/issue"
_CREATE_ADJUSTMENT_ENDPOINT = "POST /pharmacy/adjustments"
_APPROVE_ADJUSTMENT_ENDPOINT = "POST /pharmacy/adjustments/{adjustment_id}/approve"


@router.post(
    "/grn",
    response_model=GrnOut,
    status_code=201,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def create_grn_endpoint(
    payload: GrnCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> GrnOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _CREATE_GRN_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await create_grn(
        db, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _CREATE_GRN_ENDPOINT, 201, response_body, current_user.id
    )
    return result


@router.post(
    "/grn/{grn_id}/verify",
    response_model=GrnOut,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def verify_grn_endpoint(
    grn_id: UUID,
    payload: GrnVerifyRequest,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> GrnOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _VERIFY_GRN_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await verify_grn(
        db, grn_id, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _VERIFY_GRN_ENDPOINT, 200, response_body, current_user.id
    )
    return result


@router.post(
    "/indents",
    response_model=IndentOut,
    status_code=201,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin", "hod", "nurse", "doctor")),
    ],
)
async def create_indent_endpoint(
    payload: IndentCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> IndentOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _CREATE_INDENT_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await create_indent(
        db, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _CREATE_INDENT_ENDPOINT, 201, response_body, current_user.id
    )
    return result


@router.post(
    "/indents/{indent_id}/approve",
    response_model=IndentOut,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("hod")),
    ],
)
async def approve_indent_endpoint(
    indent_id: UUID,
    payload: IndentApprovalRequest,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> IndentOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _APPROVE_INDENT_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await approve_indent(
        db, indent_id, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _APPROVE_INDENT_ENDPOINT, 200, response_body, current_user.id
    )
    return result


@router.post(
    "/indents/{indent_id}/issue",
    response_model=IndentOut,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def issue_indent_endpoint(
    indent_id: UUID,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> IndentOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body({"indent_id": str(indent_id)})
    existing = await check_idempotency(
        db, idempotency_key, _ISSUE_INDENT_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await issue_indent(
        db, indent_id, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _ISSUE_INDENT_ENDPOINT, 200, response_body, current_user.id
    )
    return result


@router.get(
    "/inventory/reorder-alerts",
    response_model=ReorderAlertsResponse,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin", "hod")),
    ],
)
async def reorder_alerts_endpoint(
    current_user: CurrentDbUser,
    db: DbSession,
) -> ReorderAlertsResponse:
    return await get_reorder_alerts(db, facility_id=current_user.facility_id)


@router.post(
    "/adjustments",
    response_model=AdjustmentOut,
    status_code=201,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def create_adjustment_endpoint(
    payload: AdjustmentCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> AdjustmentOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _CREATE_ADJUSTMENT_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await create_adjustment(
        db, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _CREATE_ADJUSTMENT_ENDPOINT, 201, response_body, current_user.id
    )
    return result


@router.post(
    "/adjustments/{adjustment_id}/approve",
    response_model=AdjustmentOut,
    dependencies=[
        Depends(require_module("pharmacy")),
        Depends(require_roles("pharmacist", "admin")),
    ],
)
async def approve_adjustment_endpoint(
    adjustment_id: UUID,
    payload: AdjustmentApprovalRequest,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> AdjustmentOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    request_hash = hash_request_body(payload)
    existing = await check_idempotency(
        db, idempotency_key, _APPROVE_ADJUSTMENT_ENDPOINT, request_hash, current_user.id
    )
    if existing is not None:
        return existing.response_body
    result = await approve_adjustment(
        db, adjustment_id, payload, current_user_id=current_user.id, facility_id=current_user.facility_id,
    )
    response_body = result.model_dump(mode="json")
    await record_idempotent_response(
        db, idempotency_key, _APPROVE_ADJUSTMENT_ENDPOINT, 200, response_body, current_user.id
    )
    return result
