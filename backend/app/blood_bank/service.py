"""Blood bank service (HD-29)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blood_bank.models import BloodCrossmatch, BloodDonor, BloodUnit
from app.blood_bank.schemas import (
    BloodCrossmatchCreate,
    BloodCrossmatchOut,
    BloodDonorCreate,
    BloodDonorOut,
    BloodIssueRequest,
    BloodUnitCreate,
    BloodUnitOut,
)
from app.patients.models import Patient
from app.users.models import User
from app.common.patient_scope import actor_facility, require_patient_scope, facility_today


def donor_scope(facility_id: uuid.UUID):
    # Legacy blood tables have no facility column. Scope through the recorded
    # creator, not caller-supplied donor/patient IDs. Unowned rows fail closed.
    return select(BloodDonor.id).join(User, User.id == BloodDonor.created_by).where(User.facility_id == facility_id)


def require_issuable(unit: BloodUnit, today: date) -> None:
    if unit.status != "available" or unit.screening_status != "passed":
        raise ValueError("Blood unit is not available with passed screening")
    if unit.expiry_date < today:
        raise ValueError("Expired blood unit cannot be crossmatched or issued")


def compute_donor_eligibility(
    weight_kg: float | None,
    hemoglobin_g_dl: float | None,
    last_donation_date: date | None,
) -> tuple[bool, date | None]:
    today = date.today()
    next_date = None
    if last_donation_date:
        next_date = last_donation_date + timedelta(days=90)

    # Standard donor criteria: weight >= 45kg, Hb >= 12.5 g/dL, donation interval >= 90 days
    is_weight_ok = weight_kg is not None and weight_kg >= 45.0
    is_hb_ok = hemoglobin_g_dl is not None and hemoglobin_g_dl >= 12.5
    is_interval_ok = next_date is None or today >= next_date

    is_eligible = is_weight_ok and is_hb_ok and is_interval_ok
    return is_eligible, next_date


async def list_donors(
    db: AsyncSession,
    facility_id: uuid.UUID,
    blood_group: str | None = None,
    is_eligible: bool | None = None,
) -> list[BloodDonor]:
    query = select(BloodDonor).where(BloodDonor.id.in_(donor_scope(facility_id))).order_by(BloodDonor.full_name)
    if blood_group:
        query = query.where(BloodDonor.blood_group == blood_group.strip())
    if is_eligible is not None:
        query = query.where(BloodDonor.is_eligible == is_eligible)
    res = await db.execute(query)
    return list(res.scalars().all())


async def create_donor(
    db: AsyncSession,
    payload: BloodDonorCreate,
    user_id: uuid.UUID,
) -> BloodDonorOut:
    facility_id = await actor_facility(db, user_id)
    if payload.patient_id:
        await require_patient_scope(db, payload.patient_id, facility_id)
    is_eligible, next_eligible = compute_donor_eligibility(
        payload.weight_kg, payload.hemoglobin_g_dl, payload.last_donation_date
    )

    donor = BloodDonor(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        full_name=payload.full_name.strip(),
        sex=payload.sex,
        dob=payload.dob,
        age_years=payload.age_years,
        blood_group=payload.blood_group.strip(),
        mobile=payload.mobile,
        email=payload.email,
        address=payload.address,
        weight_kg=payload.weight_kg,
        hemoglobin_g_dl=payload.hemoglobin_g_dl,
        last_donation_date=payload.last_donation_date,
        next_eligible_date=next_eligible,
        is_eligible=is_eligible,
        remarks=payload.remarks,
        created_by=user_id,
    )
    db.add(donor)
    await db.commit()
    await db.refresh(donor)
    return BloodDonorOut.model_validate(donor)


async def list_units(
    db: AsyncSession,
    facility_id: uuid.UUID,
    status: str | None = None,
    blood_group: str | None = None,
    screening_status: str | None = None,
) -> list[BloodUnit]:
    query = select(BloodUnit).where(BloodUnit.donor_id.in_(donor_scope(facility_id))).order_by(BloodUnit.expiry_date.asc())
    if status:
        query = query.where(BloodUnit.status == status.strip())
    if blood_group:
        query = query.where(BloodUnit.blood_group == blood_group.strip())
    if screening_status:
        query = query.where(BloodUnit.screening_status == screening_status.strip())
    res = await db.execute(query)
    return list(res.scalars().all())


async def create_unit(
    db: AsyncSession,
    payload: BloodUnitCreate,
    user_id: uuid.UUID,
) -> BloodUnitOut:
    facility_id = await actor_facility(db, user_id)
    donor_res = await db.execute(select(BloodDonor).where(BloodDonor.id == payload.donor_id, BloodDonor.id.in_(donor_scope(facility_id))))
    donor = donor_res.scalar_one_or_none()
    if not donor:
        raise ValueError("Donor not found")
    if not donor.is_eligible:
        raise ValueError("Donor has not passed eligibility screening")
    if payload.expiry_date < await facility_today(db, facility_id):
        raise ValueError("Cannot add an expired blood unit")
    if payload.blood_group != donor.blood_group:
        raise ValueError("Blood group must match the donor record")

    unit = BloodUnit(
        id=uuid.uuid4(),
        donor_id=donor.id,
        bag_number=payload.bag_number.strip(),
        blood_group=payload.blood_group.strip(),
        volume_ml=payload.volume_ml,
        collected_at=datetime.now(timezone.utc),
        expiry_date=payload.expiry_date,
        screening_status=payload.screening_status,
        status="available" if payload.screening_status == "passed" else "quarantined",
    )
    db.add(unit)
    await db.commit()
    await db.refresh(unit)
    return BloodUnitOut.model_validate(unit)


async def create_crossmatch(
    db: AsyncSession,
    payload: BloodCrossmatchCreate,
    user_id: uuid.UUID,
) -> BloodCrossmatchOut:
    facility_id = await actor_facility(db, user_id)
    await require_patient_scope(db, payload.patient_id, facility_id)

    unit_res = await db.execute(select(BloodUnit).where(BloodUnit.id == payload.unit_id, BloodUnit.donor_id.in_(donor_scope(facility_id))).with_for_update())
    unit = unit_res.scalar_one_or_none()
    if not unit:
        raise ValueError(f"Blood unit {payload.unit_id} not found")
    require_issuable(unit, await facility_today(db, facility_id))

    xm = BloodCrossmatch(
        id=uuid.uuid4(),
        request_id=payload.request_id,
        patient_id=payload.patient_id,
        unit_id=payload.unit_id,
        compatibility_result=payload.compatibility_result,
        crossmatched_by=user_id,
        crossmatched_at=datetime.now(timezone.utc),
        notes=payload.notes,
    )
    db.add(xm)
    await db.commit()
    await db.refresh(xm)
    return BloodCrossmatchOut.model_validate(xm)


async def issue_blood(
    db: AsyncSession,
    payload: BloodIssueRequest,
    user_id: uuid.UUID,
) -> BloodCrossmatchOut:
    facility_id = await actor_facility(db, user_id)
    xm_res = await db.execute(select(BloodCrossmatch).join(BloodUnit, BloodUnit.id == BloodCrossmatch.unit_id).where(
        BloodCrossmatch.id == payload.crossmatch_id,
        BloodUnit.donor_id.in_(donor_scope(facility_id)),
    ).with_for_update(of=BloodCrossmatch))
    xm = xm_res.scalar_one_or_none()
    if not xm:
        raise ValueError("Crossmatch record not found")
    await require_patient_scope(db, xm.patient_id, facility_id)
    if xm.issued_at is not None:
        raise ValueError("Unit has already been issued for this crossmatch")
    if xm.compatibility_result != "compatible":
        raise ValueError(f"Cannot issue incompatible blood unit (result: {xm.compatibility_result})")

    unit_res = await db.execute(select(BloodUnit).where(BloodUnit.id == xm.unit_id).with_for_update().execution_options(populate_existing=True))
    unit = unit_res.scalar_one_or_none()
    if not unit or unit.status == "issued":
        raise ValueError("Blood unit is no longer available for issue")
    require_issuable(unit, await facility_today(db, facility_id))

    unit.status = "issued"
    unit.issued_to_patient_id = xm.patient_id
    xm.issued_at = datetime.now(timezone.utc)
    if payload.adverse_reactions:
        xm.adverse_reactions = payload.adverse_reactions
    if payload.notes:
        xm.notes = (xm.notes or "") + ("\n" + payload.notes if xm.notes else payload.notes)

    await db.commit()
    await db.refresh(xm)
    return BloodCrossmatchOut.model_validate(xm)
