"""Kitchen and diet: what each admitted patient may eat, and what they were served.

Doctors and nurses order a diet (a nurse often transcribes the dietitian's or
the doctor's advice). The kitchen board lists every admitted patient by ward
and bed with the diet in force and the day's meals; ward staff and the
services supervisor record each meal as served, refused or not served.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.dietary import service
from app.dietary.models import DIET_TYPES, MEAL_STATUSES, MEALS, DietOrder

_VIEW = ("doctor", "nurse", "admin", "hod", "supervisor")
_ORDER = ("doctor", "nurse")
_SERVE = ("nurse", "admin", "hod", "supervisor")

router = APIRouter(prefix="/dietary", tags=["dietary"], dependencies=[Depends(require_roles(*_VIEW))])

DietType = Literal[DIET_TYPES]  # type: ignore[valid-type]
Meal = Literal[MEALS]  # type: ignore[valid-type]
MealStatus = Literal[MEAL_STATUSES]  # type: ignore[valid-type]


async def _idempotency_key(idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not idempotency_key:
        raise HTTPException(400, {"code": "missing_idempotency_key", "message": "Idempotency-Key header is required"})
    return idempotency_key


def _refused(exc: service.DietError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


class DietOrderCreate(BaseModel):
    admission_id: uuid.UUID
    diet_type: DietType
    instructions: str | None = Field(default=None, max_length=1000)
    food_allergies: str | None = Field(default=None, max_length=500)


class DietStop(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class DietOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admission_id: uuid.UUID
    diet_type: str
    instructions: str | None
    food_allergies: str | None
    status: str
    starts_at: datetime
    stopped_at: datetime | None
    stop_reason: str | None


class MealCreate(BaseModel):
    admission_id: uuid.UUID
    service_date: date
    meal: Meal
    status: MealStatus
    notes: str | None = Field(default=None, max_length=500)


class MealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admission_id: uuid.UUID
    diet_order_id: uuid.UUID | None
    service_date: date
    meal: str
    status: str
    notes: str | None
    recorded_at: datetime


class BoardRow(BaseModel):
    admission_id: uuid.UUID
    ward_id: uuid.UUID
    ward_name: str
    bed_number: str
    patient_name: str | None
    uhid: str | None
    diet: DietOrderOut | None
    meals: list[MealOut]


class KitchenBoard(BaseModel):
    service_date: date
    meals: list[str]
    rows: list[BoardRow]


@router.get("/board", response_model=KitchenBoard)
async def kitchen_board(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    service_date: date | None = Query(None, alias="date"),
    ward_id: uuid.UUID | None = Query(None),
) -> KitchenBoard:
    day = service_date or service.ward_today()
    rows = await service.kitchen_board(db, current_db_user.facility_id, day, ward_id)
    return KitchenBoard(
        service_date=day,
        meals=list(MEALS),
        rows=[
            BoardRow(
                **{k: v for k, v in row.items() if k not in ("diet", "meals")},
                diet=DietOrderOut.model_validate(row["diet"]) if row["diet"] else None,
                meals=[MealOut.model_validate(m) for m in row["meals"]],
            )
            for row in rows
        ],
    )


@router.get("/admissions/{admission_id}/orders", response_model=list[DietOrderOut])
async def diet_history(
    admission_id: uuid.UUID, current_db_user: CurrentDbUser, db: AsyncSession = Depends(get_db),
) -> list[DietOrderOut]:
    try:
        await service.scoped_admission(db, admission_id, current_db_user.facility_id)
    except service.DietError as exc:
        raise _refused(exc) from None
    rows = (
        await db.execute(
            select(DietOrder).where(DietOrder.admission_id == admission_id).order_by(DietOrder.starts_at.desc())
        )
    ).scalars().all()
    return [DietOrderOut.model_validate(r) for r in rows]


@router.post("/orders", status_code=201, response_model=DietOrderOut, dependencies=[Depends(require_roles(*_ORDER))])
async def order_diet(
    payload: DietOrderCreate,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> DietOrderOut:
    endpoint, request_hash = "POST /dietary/orders", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return DietOrderOut.model_validate(cached.response_body)
    try:
        order = await service.order_diet(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id, **payload.model_dump()
        )
    except service.DietError as exc:
        raise _refused(exc) from None
    out = DietOrderOut.model_validate(order)
    await record_idempotent_response(db, idempotency_key, endpoint, 201, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/orders/{order_id}/stop", response_model=DietOrderOut, dependencies=[Depends(require_roles(*_ORDER))])
async def stop_diet(
    order_id: uuid.UUID,
    payload: DietStop,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> DietOrderOut:
    endpoint, request_hash = f"POST /dietary/orders/{order_id}/stop", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return DietOrderOut.model_validate(cached.response_body)
    try:
        order = await service.stop_diet(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id, order_id=order_id,
            reason=payload.reason,
        )
    except service.DietError as exc:
        raise _refused(exc) from None
    out = DietOrderOut.model_validate(order)
    await record_idempotent_response(db, idempotency_key, endpoint, 200, out.model_dump(mode="json"), current_db_user.id)
    return out


@router.post("/meals", status_code=201, response_model=MealOut, dependencies=[Depends(require_roles(*_SERVE))])
async def record_meal(
    payload: MealCreate,
    current_db_user: CurrentDbUser,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    db: AsyncSession = Depends(get_db),
) -> MealOut:
    endpoint, request_hash = "POST /dietary/meals", hash_request_body(payload)
    cached = await check_idempotency(db, idempotency_key, endpoint, request_hash, current_db_user.id)
    if cached is not None:
        return MealOut.model_validate(cached.response_body)
    try:
        meal = await service.record_meal(
            db, facility_id=current_db_user.facility_id, user_id=current_db_user.id, **payload.model_dump()
        )
    except service.DietError as exc:
        raise _refused(exc) from None
    out = MealOut.model_validate(meal)
    await record_idempotent_response(db, idempotency_key, endpoint, 201, out.model_dump(mode="json"), current_db_user.id)
    return out
