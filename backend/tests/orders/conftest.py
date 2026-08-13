"""
Shared fixtures for the orders/prescriptions test suite. Layered on
top of the root conftest's `db` (in-memory SQLite) and `seed`
(facility, department, room, doctor user) fixtures -- same pattern as
tests/admissions/conftest.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from app.opd.models import Encounter, Visit
from app.patients.models import Patient


async def seed_patient(db, *, facility_id: uuid.UUID, created_by: uuid.UUID) -> Patient:
    patient = Patient(
        id=uuid.uuid4(),
        facility_id=facility_id,
        full_name="Orders Test Patient",
        sex="other",
        age_years=30,
        uhid=f"IN-TS-ORD-2026-{uuid.uuid4().hex[:6]}",
        identity_path="demographics_only",
        created_by=created_by,
    )
    db.add(patient)
    await db.flush()
    return patient


async def seed_visit(db, *, facility_id: uuid.UUID, patient_id: uuid.UUID, created_by: uuid.UUID) -> Visit:
    visit = Visit(
        id=uuid.uuid4(),
        facility_id=facility_id,
        patient_id=patient_id,
        visit_number=f"V{uuid.uuid4().hex[:10]}",
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(visit)
    await db.flush()
    return visit


async def seed_encounter(
    db, *, visit_id: uuid.UUID, facility_id: uuid.UUID, provider_user_id: uuid.UUID, created_by: uuid.UUID,
) -> Encounter:
    encounter = Encounter(
        id=uuid.uuid4(),
        visit_id=visit_id,
        facility_id=facility_id,
        provider_user_id=provider_user_id,
        encounter_type="consultation",
        created_by=created_by,
    )
    db.add(encounter)
    await db.flush()
    return encounter


@pytest_asyncio.fixture
async def patient(db, seed):
    dept, _room, doctor = seed
    return await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)


@pytest_asyncio.fixture
async def visit(db, seed, patient):
    dept, _room, doctor = seed
    return await seed_visit(db, facility_id=dept.facility_id, patient_id=patient.id, created_by=doctor.id)


@pytest_asyncio.fixture
async def encounter(db, seed, visit):
    dept, _room, doctor = seed
    return await seed_encounter(
        db, visit_id=visit.id, facility_id=dept.facility_id, provider_user_id=doctor.id, created_by=doctor.id,
    )
