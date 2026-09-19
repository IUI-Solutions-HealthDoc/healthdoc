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
    blood_group: str | None = None,
    is_eligible: bool | None = None,
) -> list[BloodDonor]:
    query = select(BloodDonor).order_by(BloodDonor.full_name)
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
    status: str | None = None,
    blood_group: str | None = None,
    screening_status: str | None = None,
) -> list[BloodUnit]:
    query = select(BloodUnit).order_by(BloodUnit.expiry_date.asc())
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
) -> BloodUnitOut:
    donor_res = await db.execute(select(BloodDonor).where(BloodDonor.id == payload.donor_id))
    donor = donor_res.scalar_one_or_none()
    if not donor:
        raise ValueError(f"Donor {payload.donor_id} not found")

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
    pat_res = await db.execute(select(Patient).where(Patient.id == payload.patient_id))
    if not pat_res.scalar_one_or_none():
        raise ValueError(f"Patient {payload.patient_id} not found")

    unit_res = await db.execute(select(BloodUnit).where(BloodUnit.id == payload.unit_id))
    unit = unit_res.scalar_one_or_none()
    if not unit:
        raise ValueError(f"Blood unit {payload.unit_id} not found")
    if unit.status == "issued":
        raise ValueError(f"Blood unit {unit.bag_number} has already been issued")

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
    xm_res = await db.execute(select(BloodCrossmatch).where(BloodCrossmatch.id == payload.crossmatch_id))
    xm = xm_res.scalar_one_or_none()
    if not xm:
        raise ValueError(f"Crossmatch record {payload.crossmatch_id} not found")
    if xm.issued_at is not None:
        raise ValueError("Unit has already been issued for this crossmatch")
    if xm.compatibility_result != "compatible":
        raise ValueError(f"Cannot issue incompatible blood unit (result: {xm.compatibility_result})")

    unit_res = await db.execute(select(BloodUnit).where(BloodUnit.id == xm.unit_id))
    unit = unit_res.scalar_one_or_none()
    if not unit or unit.status == "issued":
        raise ValueError("Blood unit is no longer available for issue")

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
