"""Immunization service (HD-29)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import Facility
from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.immunization.schemas import (
    DueVaccineItem,
    ImmunizationCertificateOut,
    ImmunizationRecordCreate,
    ImmunizationRecordOut,
    PatientImmunizationScheduleOut,
)
from app.patients.models import Patient

DEFAULT_NATIONAL_VACCINES = [
    {
        "code": "BCG",
        "name": "Bacillus Calmette–Guérin (BCG)",
        "target_disease": "Tuberculosis",
        "standard_doses": 1,
        "min_age_days": 0,
        "max_age_days": 365,
        "route": "intradermal",
        "site": "left_upper_arm",
        "dose_quantity": "0.05 ml",
    },
    {
        "code": "OPV-0",
        "name": "Oral Polio Vaccine Birth Dose",
        "target_disease": "Poliomyelitis",
        "standard_doses": 1,
        "min_age_days": 0,
        "max_age_days": 15,
        "route": "oral",
        "site": "oral",
        "dose_quantity": "2 drops",
    },
    {
        "code": "HEPB-0",
        "name": "Hepatitis B Birth Dose",
        "target_disease": "Hepatitis B",
        "standard_doses": 1,
        "min_age_days": 0,
        "max_age_days": 1,
        "route": "intramuscular",
        "site": "anterolateral_thigh",
        "dose_quantity": "0.5 ml",
    },
    {
        "code": "PENTAVALENT-1",
        "name": "Pentavalent Dose 1 (DPT + HepB + Hib)",
        "target_disease": "Diphtheria, Pertussis, Tetanus, Hep B, Hib",
        "standard_doses": 1,
        "min_age_days": 42,
        "max_age_days": 365,
        "route": "intramuscular",
        "site": "anterolateral_thigh",
        "dose_quantity": "0.5 ml",
    },
    {
        "code": "ROTA-1",
        "name": "Rotavirus Vaccine Dose 1",
        "target_disease": "Rotavirus Diarrhoea",
        "standard_doses": 1,
        "min_age_days": 42,
        "max_age_days": 365,
        "route": "oral",
        "site": "oral",
        "dose_quantity": "5 drops",
    },
    {
        "code": "PCV-1",
        "name": "Pneumococcal Conjugate Vaccine Dose 1",
        "target_disease": "Pneumococcal Disease",
        "standard_doses": 1,
        "min_age_days": 42,
        "max_age_days": 365,
        "route": "intramuscular",
        "site": "anterolateral_thigh",
        "dose_quantity": "0.5 ml",
    },
    {
        "code": "MEASLES-1",
        "name": "Measles & Rubella (MR) Dose 1",
        "target_disease": "Measles, Rubella",
        "standard_doses": 1,
        "min_age_days": 270,
        "max_age_days": 1825,
        "route": "subcutaneous",
        "site": "right_upper_arm",
        "dose_quantity": "0.5 ml",
    },
    {
        "code": "DPT-BOOSTER-1",
        "name": "DPT Booster 1",
        "target_disease": "Diphtheria, Pertussis, Tetanus",
        "standard_doses": 1,
        "min_age_days": 480,
        "max_age_days": 2555,
        "route": "intramuscular",
        "site": "anterolateral_thigh",
        "dose_quantity": "0.5 ml",
    },
    {
        "code": "TD",
        "name": "Tetanus and Adult Diphtheria (Td)",
        "target_disease": "Tetanus, Diphtheria",
        "standard_doses": 1,
        "min_age_days": 3650,
        "max_age_days": None,
        "route": "intramuscular",
        "site": "upper_arm",
        "dose_quantity": "0.5 ml",
    },
]


async def ensure_catalogue_seeded(db: AsyncSession) -> None:
    try:
        res = await db.execute(select(VaccineCatalogue).limit(1))
        if res.scalars().first() is None:
            for item in DEFAULT_NATIONAL_VACCINES:
                vc = VaccineCatalogue(id=uuid.uuid4(), **item)
                db.add(vc)
            await db.commit()
    except Exception:
        await db.rollback()


async def get_catalogue(db: AsyncSession) -> list[VaccineCatalogue]:
    await ensure_catalogue_seeded(db)
    res = await db.execute(
        select(VaccineCatalogue).where(VaccineCatalogue.is_active == True).order_by(VaccineCatalogue.min_age_days)
    )
    return list(res.scalars().all())


async def get_patient_schedule(db: AsyncSession, patient_id: uuid.UUID) -> PatientImmunizationScheduleOut:
    await ensure_catalogue_seeded(db)
    pat_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = pat_res.scalar_one_or_none()
    if not patient:
        raise ValueError(f"Patient {patient_id} not found")

    rec_res = await db.execute(
        select(ImmunizationRecord)
        .where(ImmunizationRecord.patient_id == patient_id)
        .order_by(ImmunizationRecord.administered_at)
    )
    records = list(rec_res.scalars().all())

    administered_outs = [ImmunizationRecordOut.model_validate(r) for r in records]
    administered_map: dict[str, set[int]] = {}
    for r in records:
        administered_map.setdefault(r.vaccine_code.upper(), set()).add(r.dose_number)

    cat = await get_catalogue(db)
    due_items: list[DueVaccineItem] = []

    today = date.today()
    dob = patient.dob
    age_days = (today - dob).days if dob else None

    for vac in cat:
        vcode = vac.code.upper()
        done_doses = administered_map.get(vcode, set())
        for d in range(1, vac.standard_doses + 1):
            if d not in done_doses:
                due_date = None
                status = "due"
                if dob:
                    due_date = dob + timedelta(days=vac.min_age_days)
                    if today < due_date:
                        status = "upcoming"
                    elif today > due_date + timedelta(days=30):
                        status = "overdue"
                    else:
                        status = "due"
                due_items.append(
                    DueVaccineItem(
                        vaccine_code=vac.code,
                        vaccine_name=vac.name,
                        dose_number=d,
                        target_disease=vac.target_disease,
                        min_age_days=vac.min_age_days,
                        status=status,
                        due_date=due_date,
                    )
                )

    return PatientImmunizationScheduleOut(
        patient_id=patient.id,
        patient_name=patient.full_name,
        dob=patient.dob,
        age_days=age_days,
        administered=administered_outs,
        due=due_items,
    )


async def record_administration(
    db: AsyncSession, payload: ImmunizationRecordCreate, user_id: uuid.UUID
) -> ImmunizationRecordOut:
    await ensure_catalogue_seeded(db)
    vac_res = await db.execute(
        select(VaccineCatalogue).where(VaccineCatalogue.code.ilike(payload.vaccine_code.strip()))
    )
    vaccine = vac_res.scalar_one_or_none()
    if not vaccine:
        raise ValueError(f"Vaccine with code {payload.vaccine_code} not found in catalogue")

    rec = ImmunizationRecord(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        vaccine_id=vaccine.id,
        vaccine_code=vaccine.code,
        dose_number=payload.dose_number,
        administered_at=payload.administered_at or datetime.now(timezone.utc),
        batch_number=payload.batch_number.strip(),
        expiry_date=payload.expiry_date,
        manufacturer=payload.manufacturer,
        site=payload.site or vaccine.site,
        route=payload.route or vaccine.route,
        administered_by=user_id,
        adverse_reaction=payload.adverse_reaction,
        notes=payload.notes,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return ImmunizationRecordOut.model_validate(rec)


async def generate_certificate(
    db: AsyncSession, patient_id: uuid.UUID, facility_id: uuid.UUID | None
) -> ImmunizationCertificateOut:
    pat_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = pat_res.scalar_one_or_none()
    if not patient:
        raise ValueError(f"Patient {patient_id} not found")

    rec_res = await db.execute(
        select(ImmunizationRecord)
        .where(ImmunizationRecord.patient_id == patient_id)
        .order_by(ImmunizationRecord.administered_at)
    )
    records = [ImmunizationRecordOut.model_validate(r) for r in rec_res.scalars().all()]

    facility_name = "HealthDoc General Hospital"
    if facility_id:
        f_res = await db.execute(select(Facility).where(Facility.id == facility_id))
        fac = f_res.scalar_one_or_none()
        if fac:
            facility_name = fac.name

    cert_id = f"IMM-CERT-{str(patient.id)[:8].upper()}-{datetime.now(timezone.utc):%Y%m%d}"

    return ImmunizationCertificateOut(
        patient_id=patient.id,
        patient_name=patient.full_name,
        dob=patient.dob,
        gender=getattr(patient, "sex", None),
        abha_number=getattr(patient, "abha_number", None),
        facility_name=facility_name,
        certificate_id=cert_id,
        generated_at=datetime.now(timezone.utc),
        records=records,
    )
