"""Patient history aggregation service — W3-01 (#179).

Repo path: backend/app/patients/history_service.py

Role-filtered:
  - doctor:             visits + encounters (SOAP) + diagnoses + prescriptions + labs + radiology
  - nurse:              visits + encounters (SOAP stripped)
  - receptionist/admin: visits only
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.opd.models import Diagnosis, Encounter, Visit
from app.orders.models import Order, Prescription
from app.pathology.models import LabOrderItem, LabResult
from app.radiology.models import RadiologyOrderItem, RadiologyReport


_FULL_ACCESS_ROLES = {"doctor"}
_ENCOUNTER_ROLES = {"nurse"}


def _role_tier(role: str) -> str:
    if role in _FULL_ACCESS_ROLES:
        return "full"
    if role in _ENCOUNTER_ROLES:
        return "encounter"
    return "visit"


async def _get_visits(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(Visit)
            .where(Visit.patient_id == patient_id)
            .order_by(Visit.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "visit_id": str(v.id),
            "visit_number": v.visit_number,
            "visit_type": v.visit_type,
            "status": v.status,
            "started_at": v.visit_date.isoformat() if v.visit_date else None,
        }
        for v in rows
    ]


async def _get_encounters(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(Encounter)
            .join(Visit, Visit.id == Encounter.visit_id)
            .where(Visit.patient_id == patient_id)
            .order_by(Encounter.started_at.desc())
        )
    ).scalars().all()
    return [
        {
            "encounter_id": str(e.id),
            "visit_id": str(e.visit_id),
            "encounter_type": e.encounter_type,
            "chief_complaint": e.chief_complaint,
            "note_status": e.note_status,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "ended_at": e.ended_at.isoformat() if e.ended_at else None,
            "subjective": e.subjective,
            "objective": e.objective,
            "assessment": e.assessment,
            "plan": e.plan,
        }
        for e in rows
    ]


async def _get_diagnoses(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(Diagnosis)
            .join(Encounter, Encounter.id == Diagnosis.encounter_id)
            .join(Visit, Visit.id == Encounter.visit_id)
            .where(Visit.patient_id == patient_id)
            .order_by(Diagnosis.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "diagnosis_id": str(d.id),
            "encounter_id": str(d.encounter_id),
            "icd_code": d.icd_code,
            "diagnosis_text": d.diagnosis_text,
            "diagnosis_type": d.diagnosis_type,
            "is_primary": d.is_primary,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


async def _get_prescriptions(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(Prescription)
            .where(Prescription.patient_id == patient_id)
            .order_by(Prescription.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "prescription_id": str(p.id),
            "encounter_id": str(p.encounter_id),
            "notes": p.notes,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


async def _get_lab_results(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(LabResult)
            .join(LabOrderItem, LabOrderItem.id == LabResult.lab_order_item_id)
            .join(Order, Order.id == LabOrderItem.order_id)
            .where(Order.patient_id == patient_id)
            .where(LabResult.is_current == True)
            .order_by(LabResult.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "result_id": str(r.id),
            "lab_order_item_id": str(r.lab_order_item_id),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def _get_radiology_reports(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            sa.select(RadiologyReport)
            .join(RadiologyOrderItem, RadiologyOrderItem.id == RadiologyReport.radiology_order_item_id)
            .join(Order, Order.id == RadiologyOrderItem.order_id)
            .where(Order.patient_id == patient_id)
            .where(RadiologyReport.is_current == True)
            .order_by(RadiologyReport.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "report_id": str(r.id),
            "radiology_order_item_id": str(r.radiology_order_item_id),
            "status": r.status,
            "findings": r.findings,
            "impression": r.impression,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def get_patient_history(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    role: str,
) -> dict[str, Any]:
    tier = _role_tier(role)
    visits = await _get_visits(db, patient_id)
    result: dict[str, Any] = {"visits": visits}

    if tier in ("encounter", "full"):
        encounters = await _get_encounters(db, patient_id)
        if tier == "encounter":
            for e in encounters:
                e.pop("subjective", None)
                e.pop("objective", None)
                e.pop("assessment", None)
                e.pop("plan", None)
        result["encounters"] = encounters

    if tier == "full":
        result["diagnoses"] = await _get_diagnoses(db, patient_id)
        result["prescriptions"] = await _get_prescriptions(db, patient_id)
        result["lab_results"] = await _get_lab_results(db, patient_id)
        result["radiology_reports"] = await _get_radiology_reports(db, patient_id)

    return result
