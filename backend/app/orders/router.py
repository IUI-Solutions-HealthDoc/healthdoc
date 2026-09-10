"""backend/app/orders/router.py -- /orders endpoints. created_by comes
from current_db_user, never the request body."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies.service import AllergyConflict
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.orders import results_worklist, service
from app.orders.external_referrals import ReferralState, list_external_referrals
from app.orders.schemas import (
    ExternalReferralListOut,
    ExternalResultCreate,
    ExternalResultListOut,
    ExternalResultOut,
    OrderCreate,
    OrderListOut,
    OrderOut,
    PrescriptionCreate,
    PrescriptionItemOut,
    PrescriptionOut,
    ResultWorklistItemOut,
    ResultWorklistOut,
)

router = APIRouter(prefix="/orders", tags=["orders"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
_EXTERNAL_RESULT_ROLES = ("doctor", "nurse", "admin")


@router.post("", response_model=OrderOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_order(payload: OrderCreate, current_db_user: CurrentDbUser,
                        db: AsyncSession = Depends(get_db),
                        idempotency_key: Annotated[
                            str | None, Header(alias="Idempotency-Key")
                        ] = None) -> OrderOut:
    """No facility lookup here (see #362) -- create_order() resolves
    the business-date timezone from the encounter's own facility now,
    not the caller's. current_db_user.facility_id was never the right
    facility for this: it's whoever is logged in, which can legitimately
    differ from the facility the encounter/order actually belongs to.

    created_by, however, IS the caller's. It used to be a required body field
    written straight to orders.created_by, so any caller could file a lab test
    or a scan under a colleague's name — contradicting this module's docstring.
    A disagreeing body value is refused rather than silently overridden, so an
    attempted misattribution leaves a trace.
    """
    if payload.created_by is not None and payload.created_by != current_db_user.id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "code": "created_by_mismatch",
                "message": "created_by must be the authenticated user",
            },
        )
    payload.created_by = current_db_user.id

    endpoint = "POST /orders"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return OrderOut.model_validate(cached.response_body)

    try:
        order = await service.create_order(db, payload)
    except service.EncounterNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    except service.PatientMismatch:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "patient_mismatch",
                "message": "patient_id does not belong to the encounter's visit",
            },
        )
    response = OrderOut.model_validate(order)
    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            http_status.HTTP_201_CREATED,
            response.model_dump(mode="json"),
            current_db_user.id,
        )
    return response


@router.get("", response_model=OrderListOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def list_orders(
    current_db_user: CurrentDbUser,
    encounter_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> OrderListOut:
    rows = await service.list_orders_for_encounter(
        db, encounter_id, current_db_user.facility_id,
    )
    return OrderListOut(items=[OrderOut.model_validate(row) for row in rows])


@router.get("/results-worklist", response_model=ResultWorklistOut,
            dependencies=[Depends(require_roles("doctor", "admin"))],
            summary="Lab and radiology results awaiting this doctor's review")
async def get_results_worklist(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ResultWorklistOut:
    """The doctor's outstanding results, lab and radiology ranked together.

    Registered BEFORE GET /{order_id}: both are one segment under /orders, so
    whichever is declared first wins, and "results-worklist" parsed as a UUID
    is a 422 that reads like a validation bug rather than a routing one.

    Scope follows queue.service.get_doctor_worklist — a doctor sees the orders
    they placed, an admin sees the facility. It is derived from the caller's
    roles, never from a query parameter: a doctor able to pass `all=true` would
    be reading colleagues' worklists, which is the thing the scope prevents.
    """
    rows = await results_worklist.get_results_worklist(
        db,
        caller_id=current_db_user.id,
        facility_id=current_db_user.facility_id,
        caller_roles=current_db_user.roles,
    )
    return ResultWorklistOut(
        items=[ResultWorklistItemOut(**row) for row in rows]
    )


@router.get("/external-referrals", response_model=ExternalReferralListOut,
            dependencies=[Depends(require_roles("doctor", "admin"))])
async def get_external_referrals(
    current_db_user: CurrentDbUser,
    db: DbSession,
    state: Annotated[ReferralState, Query()] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExternalReferralListOut:
    """Pending/completed referrals across visits, including closed encounters."""
    return await list_external_referrals(
        db, caller_id=current_db_user.id, facility_id=current_db_user.facility_id,
        caller_roles=current_db_user.roles, state=state, limit=limit, offset=offset,
    )


@router.post(
    "/{order_id}/external-results",
    response_model=ExternalResultOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_EXTERNAL_RESULT_ROLES))],
)
async def create_external_result(
    order_id: UUID,
    payload: ExternalResultCreate,
    current_db_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=255)
    ] = None,
) -> ExternalResultOut:
    # An idempotency response is still patient data. Recheck ownership before
    # replay so an account moved between facilities cannot read its old work.
    order = await service.get_order(db, order_id)
    if order is None or order.facility_id != current_db_user.facility_id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="order_not_found")
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    endpoint = f"POST /orders/{order_id}/external-results"
    request_hash = hash_request_body(payload)
    cached = await check_idempotency(
        db, idempotency_key, endpoint, request_hash, current_db_user.id
    )
    if cached is not None:
        return ExternalResultOut.model_validate(cached.response_body)

    try:
        result = await service.record_external_result(
            db,
            order_id=order_id,
            payload=payload,
            facility_id=current_db_user.facility_id,
            recorded_by=current_db_user.id,
        )
    except service.ExternalResultOrderNotFound:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="order_not_found"
        ) from None
    except service.ExternalResultConflict as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"code": exc.code},
        ) from exc
    except service.ExternalResultFileInvalid as exc:
        if exc.code == "result_file_not_found":
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="result_file_not_found",
            ) from exc
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code},
        ) from exc

    response = ExternalResultOut.model_validate(result)
    await record_idempotent_response(
        db,
        idempotency_key,
        endpoint,
        http_status.HTTP_201_CREATED,
        response.model_dump(mode="json"),
        current_db_user.id,
    )
    return response


@router.get(
    "/{order_id}/external-results",
    response_model=ExternalResultListOut,
    dependencies=[Depends(require_roles(*_EXTERNAL_RESULT_ROLES))],
)
async def get_external_results(
    order_id: UUID,
    current_db_user: CurrentDbUser,
    db: DbSession,
) -> ExternalResultListOut:
    try:
        rows = await service.list_external_results(
            db, order_id=order_id, facility_id=current_db_user.facility_id
        )
    except service.ExternalResultOrderNotFound:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="order_not_found"
        ) from None
    return ExternalResultListOut(
        items=[ExternalResultOut.model_validate(row) for row in rows]
    )


@router.get("/{order_id}", response_model=OrderOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def get_order(order_id: UUID, current_db_user: CurrentDbUser,
                     db: AsyncSession = Depends(get_db)) -> OrderOut:
    order = await service.get_order(db, order_id)
    # orders.facility_id has existed since 0022 and nothing was reading it here.
    # 404 rather than 403 — 403 confirms the id exists.
    if order is None or order.facility_id != current_db_user.facility_id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order_not_found")
    return OrderOut.model_validate(order)


@router.post("/prescriptions", response_model=PrescriptionOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "admin"))])
async def create_prescription(payload: PrescriptionCreate, current_db_user: CurrentDbUser,
                               db: AsyncSession = Depends(get_db)) -> PrescriptionOut:
    """created_by is taken from current_db_user, never the request body
    (PrescriptionCreate deliberately has no created_by field, unlike
    OrderCreate). AllergyConflict -> 409: retry the same request with
    override_reason set on the conflicting item (>=20 chars) unless the
    allergy is anaphylaxis, which can never be overridden by any role.
    Interaction warnings never block -- they come back on a 201 inside
    the response body, not as an error."""
    try:
        prescription, warnings = await service.create_prescription(
            db, payload, current_db_user.id,
        )
    except service.EncounterNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    except AllergyConflict as e:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": "allergy_conflict",
                "message": str(e),
                "absolute": e.absolute,
                "allergy_id": str(e.allergy.id),
            },
        )
    items = await service.get_prescription_items(db, prescription.id)
    return PrescriptionOut(
        id=prescription.id, encounter_id=prescription.encounter_id, facility_id=prescription.facility_id,
        patient_id=prescription.patient_id, notes=prescription.notes,
        created_at=prescription.created_at, updated_at=prescription.updated_at,
        items=[PrescriptionItemOut.model_validate(i) for i in items],
        interaction_warnings=warnings,
    )


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "pharmacist", "admin"))])
async def get_prescription(prescription_id: UUID, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db)) -> PrescriptionOut:
    prescription = await service.get_prescription(
        db, prescription_id, current_db_user.facility_id
    )
    if prescription is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="prescription_not_found")
    items = await service.get_prescription_items(db, prescription_id)
    return PrescriptionOut(
        id=prescription.id, encounter_id=prescription.encounter_id, facility_id=prescription.facility_id,
        patient_id=prescription.patient_id, notes=prescription.notes,
        created_at=prescription.created_at, updated_at=prescription.updated_at,
        items=[PrescriptionItemOut.model_validate(i) for i in items],
    )
