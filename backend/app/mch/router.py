"""Maternal and child health: pregnancy, ANC visits, delivery and newborns.

Record only (see app/mch/models.py). Doctors and nurses write; every write is
an atomic clinical write with an Idempotency-Key, scoped to the caller's
facility (another facility's pregnancy is 404).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.common.clinical_write import ClinicalWriteKey, clinical_write
from app.common.patient_scope import facility_today, require_patient_access
from app.mch.models import AncVisit, Delivery, Newborn, Pregnancy

_WRITE = ("doctor", "nurse")
router = APIRouter(prefix="/mch", tags=["mch"], dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])


# ------------------------------------------------------------------ shapes


class PregnancyCreate(BaseModel):
    patient_id: uuid.UUID
    lmp_date: date | None = None
    edd: date | None = None
    gravida: int | None = Field(default=None, ge=1, le=20)
    para: int | None = Field(default=None, ge=0, le=20)
    rch_id: str | None = Field(default=None, max_length=30)


class RiskFlag(BaseModel):
    high_risk: bool
    reason: str | None = Field(default=None, max_length=500)


class PregnancyEnd(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AncVisitCreate(BaseModel):
    visit_date: date
    gestation_weeks: int | None = Field(default=None, ge=1, le=45)
    weight_kg: Decimal | None = Field(default=None, ge=20, le=250, max_digits=5, decimal_places=1)
    bp_systolic: int | None = Field(default=None, ge=50, le=260)
    bp_diastolic: int | None = Field(default=None, ge=20, le=180)
    hemoglobin_g_dl: Decimal | None = Field(default=None, ge=2, le=22, max_digits=4, decimal_places=1)
    fundal_height_cm: int | None = Field(default=None, ge=5, le=50)
    fetal_heart_rate: int | None = Field(default=None, ge=50, le=240)
    urine_albumin: Literal["nil", "trace", "+", "++", "+++"] | None = None
    urine_sugar: Literal["nil", "trace", "+", "++", "+++"] | None = None
    ifa_tablets: int | None = Field(default=None, ge=0, le=400)
    notes: str | None = Field(default=None, max_length=1000)


class NewbornIn(BaseModel):
    outcome: Literal["live_birth", "still_birth"]
    sex: Literal["male", "female", "other", "unknown"]
    birth_weight_g: int | None = Field(default=None, ge=200, le=7000)


class DeliveryCreate(BaseModel):
    delivered_at: datetime
    mode: Literal["normal", "assisted", "caesarean"]
    notes: str | None = Field(default=None, max_length=1000)
    newborns: list[NewbornIn] = Field(min_length=1, max_length=6)


class AncVisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    visit_date: date
    gestation_weeks: int | None
    weight_kg: Decimal | None
    bp_systolic: int | None
    bp_diastolic: int | None
    hemoglobin_g_dl: Decimal | None
    fundal_height_cm: int | None
    fetal_heart_rate: int | None
    urine_albumin: str | None
    urine_sugar: str | None
    ifa_tablets: int | None
    notes: str | None


class NewbornOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    outcome: str
    sex: str
    birth_weight_g: int | None
    patient_id: uuid.UUID | None


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    delivered_at: datetime
    mode: str
    notes: str | None
    newborns: list[NewbornOut] = []


class PregnancyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    patient_id: uuid.UUID
    lmp_date: date | None
    edd: date | None
    gravida: int | None
    para: int | None
    rch_id: str | None
    status: str
    high_risk: bool
    high_risk_reason: str | None
    end_reason: str | None
    created_at: datetime
    anc_visits: list[AncVisitOut] = []
    delivery: DeliveryOut | None = None


# ------------------------------------------------------------------ helpers


async def _full(db: AsyncSession, pregnancy: Pregnancy) -> PregnancyOut:
    visits = (
        await db.execute(
            select(AncVisit).where(AncVisit.pregnancy_id == pregnancy.id).order_by(AncVisit.visit_date, AncVisit.created_at)
        )
    ).scalars().all()
    delivery = (await db.execute(select(Delivery).where(Delivery.pregnancy_id == pregnancy.id))).scalar_one_or_none()
    delivery_out = None
    if delivery is not None:
        babies = (await db.execute(select(Newborn).where(Newborn.delivery_id == delivery.id))).scalars().all()
        delivery_out = DeliveryOut.model_validate(delivery).model_copy(
            update={"newborns": [NewbornOut.model_validate(b) for b in babies]}
        )
    return PregnancyOut.model_validate(pregnancy).model_copy(
        update={"anc_visits": [AncVisitOut.model_validate(v) for v in visits], "delivery": delivery_out}
    )


async def _scoped(db: AsyncSession, pregnancy_id: uuid.UUID, user, *, lock: bool = False) -> Pregnancy:
    stmt = select(Pregnancy).where(Pregnancy.id == pregnancy_id, Pregnancy.facility_id == user.facility_id)
    if lock:
        stmt = stmt.with_for_update()
    pregnancy = (await db.execute(stmt)).scalar_one_or_none()
    if pregnancy is None:
        raise HTTPException(404, {"code": "pregnancy_not_found", "message": "Pregnancy record not found"})
    await require_patient_access(db, pregnancy.patient_id, user)
    return pregnancy


def _require_writer(user) -> None:
    if not set(_WRITE) & set(user.roles):
        raise HTTPException(403, {"code": "mch_write_forbidden", "message": "Doctors and nurses record maternal care"})


def _require_active(pregnancy: Pregnancy) -> None:
    if pregnancy.status != "active":
        raise HTTPException(409, {"code": "pregnancy_closed", "message": f"This pregnancy is {pregnancy.status}"})


# ------------------------------------------------------------------ routes


@router.get("/patients/{patient_id}/pregnancies", response_model=list[PregnancyOut])
async def list_pregnancies(patient_id: uuid.UUID, current_user: CurrentDbUser, db: DbSession) -> list[PregnancyOut]:
    await require_patient_access(db, patient_id, current_user)
    rows = (
        await db.execute(
            select(Pregnancy)
            .where(Pregnancy.patient_id == patient_id, Pregnancy.facility_id == current_user.facility_id)
            .order_by(Pregnancy.created_at.desc())
        )
    ).scalars().all()
    return [await _full(db, p) for p in rows]


@router.post("/pregnancies", response_model=PregnancyOut, status_code=201)
async def register_pregnancy(
    payload: PregnancyCreate, current_user: CurrentDbUser, db: DbSession, idempotency_key: ClinicalWriteKey,
) -> PregnancyOut:
    _require_writer(current_user)
    await require_patient_access(db, payload.patient_id, current_user)

    async def write() -> PregnancyOut:
        today = await facility_today(db, current_user.facility_id)
        if payload.lmp_date and payload.lmp_date > today:
            raise HTTPException(422, {"code": "lmp_in_future", "message": "The last menstrual period cannot be in the future"})
        open_one = (
            await db.execute(
                select(Pregnancy.id).where(
                    Pregnancy.patient_id == payload.patient_id, Pregnancy.facility_id == current_user.facility_id,
                    Pregnancy.status == "active",
                )
            )
        ).first()
        if open_one is not None:
            raise HTTPException(409, {"code": "pregnancy_already_active", "message": "Close the current pregnancy first"})
        pregnancy = Pregnancy(
            id=uuid.uuid4(), facility_id=current_user.facility_id, patient_id=payload.patient_id,
            lmp_date=payload.lmp_date, edd=payload.edd, gravida=payload.gravida, para=payload.para,
            rch_id=(payload.rch_id or "").strip() or None, status="active", created_by=current_user.id,
        )
        db.add(pregnancy)
        await db.flush()
        return await _full(db, pregnancy)

    return await clinical_write(db, idempotency_key, "POST /mch/pregnancies", payload, current_user, PregnancyOut, write)


@router.post("/pregnancies/{pregnancy_id}/risk", response_model=PregnancyOut)
async def flag_risk(
    pregnancy_id: uuid.UUID, payload: RiskFlag, current_user: CurrentDbUser, db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> PregnancyOut:
    _require_writer(current_user)
    pregnancy = await _scoped(db, pregnancy_id, current_user, lock=True)

    async def write() -> PregnancyOut:
        reason = (payload.reason or "").strip() or None
        if payload.high_risk and reason is None:
            raise HTTPException(422, {"code": "risk_reason_required", "message": "Say why this pregnancy is high risk"})
        pregnancy.high_risk, pregnancy.high_risk_reason = payload.high_risk, reason if payload.high_risk else None
        await db.flush()
        return await _full(db, pregnancy)

    return await clinical_write(
        db, idempotency_key, f"POST /mch/pregnancies/{pregnancy_id}/risk", payload, current_user, PregnancyOut,
        write, status=200,
    )


@router.post("/pregnancies/{pregnancy_id}/end", response_model=PregnancyOut)
async def end_pregnancy(
    pregnancy_id: uuid.UUID, payload: PregnancyEnd, current_user: CurrentDbUser, db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> PregnancyOut:
    """Close a pregnancy that did not end in a delivery here (loss, transfer out)."""
    _require_writer(current_user)
    pregnancy = await _scoped(db, pregnancy_id, current_user, lock=True)

    async def write() -> PregnancyOut:
        _require_active(pregnancy)
        pregnancy.status, pregnancy.end_reason = "ended", payload.reason.strip()
        await db.flush()
        return await _full(db, pregnancy)

    return await clinical_write(
        db, idempotency_key, f"POST /mch/pregnancies/{pregnancy_id}/end", payload, current_user, PregnancyOut,
        write, status=200,
    )


@router.post("/pregnancies/{pregnancy_id}/anc-visits", response_model=PregnancyOut, status_code=201)
async def record_anc_visit(
    pregnancy_id: uuid.UUID, payload: AncVisitCreate, current_user: CurrentDbUser, db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> PregnancyOut:
    _require_writer(current_user)
    pregnancy = await _scoped(db, pregnancy_id, current_user, lock=True)

    async def write() -> PregnancyOut:
        _require_active(pregnancy)
        if payload.visit_date > await facility_today(db, current_user.facility_id):
            raise HTTPException(422, {"code": "visit_in_future", "message": "A visit cannot be recorded for a future day"})
        if (payload.bp_systolic is None) != (payload.bp_diastolic is None):
            raise HTTPException(422, {"code": "bp_incomplete", "message": "Record both systolic and diastolic, or neither"})
        db.add(AncVisit(
            id=uuid.uuid4(), pregnancy_id=pregnancy.id, facility_id=current_user.facility_id,
            recorded_by=current_user.id, **payload.model_dump(),
        ))
        await db.flush()
        return await _full(db, pregnancy)

    return await clinical_write(
        db, idempotency_key, f"POST /mch/pregnancies/{pregnancy_id}/anc-visits", payload, current_user,
        PregnancyOut, write,
    )


@router.post("/pregnancies/{pregnancy_id}/delivery", response_model=PregnancyOut, status_code=201)
async def record_delivery(
    pregnancy_id: uuid.UUID, payload: DeliveryCreate, current_user: CurrentDbUser, db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> PregnancyOut:
    _require_writer(current_user)
    pregnancy = await _scoped(db, pregnancy_id, current_user, lock=True)

    async def write() -> PregnancyOut:
        _require_active(pregnancy)
        if payload.delivered_at.tzinfo is None:
            raise HTTPException(422, {"code": "delivered_at_needs_zone", "message": "Send the time with its time zone"})
        if payload.delivered_at > datetime.now(UTC):
            raise HTTPException(422, {"code": "delivery_in_future", "message": "A delivery cannot be in the future"})
        delivery = Delivery(
            id=uuid.uuid4(), pregnancy_id=pregnancy.id, facility_id=current_user.facility_id,
            delivered_at=payload.delivered_at, mode=payload.mode, notes=payload.notes, recorded_by=current_user.id,
        )
        db.add(delivery)
        await db.flush()
        db.add_all(
            Newborn(id=uuid.uuid4(), delivery_id=delivery.id, facility_id=current_user.facility_id, **baby.model_dump())
            for baby in payload.newborns
        )
        pregnancy.status = "delivered"
        await db.flush()
        return await _full(db, pregnancy)

    return await clinical_write(
        db, idempotency_key, f"POST /mch/pregnancies/{pregnancy_id}/delivery", payload, current_user,
        PregnancyOut, write,
    )
