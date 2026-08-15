"""
Shared fixtures for the admissions test suite.

Unlike billing, this module does NOT need real Postgres. The two
integrity rules added in migration 0034 -- uq_admissions_active_bed
(partial unique index) and ck_discharges_transfer_destination (CHECK
constraint) -- are both plain SQL, and app/admissions/models.py already
declares sqlite_where alongside postgresql_where for the partial index
specifically so SQLite enforces the same rule. That means the repo's
shared in-memory SQLite fixtures (tests/conftest.py: `db`, `seed`)
are sufficient here.

Patient/Visit are real ORM models already registered on Base.metadata,
so they're built via the ORM here rather than raw sa.text() inserts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from app.admissions.models import Admission, Bed, Ward
from app.opd.models import Visit
from app.patients.models import Patient


async def seed_ward(db, *, facility_id: uuid.UUID, department_id: uuid.UUID | None = None, name: str = "Test Ward") -> Ward:
    ward = Ward(id=uuid.uuid4(), name=name, facility_id=facility_id, department_id=department_id)
    db.add(ward)
    await db.flush()
    return ward


async def seed_bed(db, *, ward_id: uuid.UUID, bed_number: str = "1") -> Bed:
    bed = Bed(id=uuid.uuid4(), ward_id=ward_id, bed_number=bed_number)
    db.add(bed)
    await db.flush()
    return bed


async def seed_patient(db, *, facility_id: uuid.UUID, created_by: uuid.UUID) -> Patient:
    patient = Patient(
        id=uuid.uuid4(),
        facility_id=facility_id,
        full_name="Admissions Test Patient",
        sex="other",
        age_years=30,
        uhid=f"IN-TS-ADM-2026-{uuid.uuid4().hex[:6]}",
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
        visit_type="ipd",
        visit_date=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(visit)
    await db.flush()
    return visit


async def seed_admission(
    db, *, visit_id: uuid.UUID, patient_id: uuid.UUID, ward_id: uuid.UUID, bed_id: uuid.UUID,
    created_by: uuid.UUID, status: str = "admitted",
) -> Admission:
    admission = Admission(
        id=uuid.uuid4(),
        visit_id=visit_id,
        patient_id=patient_id,
        ward_id=ward_id,
        bed_id=bed_id,
        admitted_at=datetime.now(timezone.utc),
        status=status,
        created_by=created_by,
    )
    db.add(admission)
    await db.flush()
    return admission


@pytest_asyncio.fixture
async def ward(db, seed):
    dept, _room, _doctor = seed
    return await seed_ward(db, facility_id=dept.facility_id, department_id=dept.id)


@pytest_asyncio.fixture
async def bed(db, ward):
    return await seed_bed(db, ward_id=ward.id)


@pytest_asyncio.fixture
async def patient(db, seed):
    dept, _room, doctor = seed
    return await seed_patient(db, facility_id=dept.facility_id, created_by=doctor.id)


@pytest_asyncio.fixture
async def visit(db, seed, patient):
    dept, _room, doctor = seed
    return await seed_visit(db, facility_id=dept.facility_id, patient_id=patient.id, created_by=doctor.id)


@pytest_asyncio.fixture
async def admission(db, seed, visit, patient, ward, bed):
    _dept, _room, doctor = seed
    return await seed_admission(
        db, visit_id=visit.id, patient_id=patient.id, ward_id=ward.id, bed_id=bed.id,
        created_by=doctor.id,
    )
