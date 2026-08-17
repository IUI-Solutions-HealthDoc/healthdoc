from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncGenerator
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# NB: a `pytestmark` in a conftest applies to that conftest, not to the test
# modules beside it — so it never skipped anything. The skip has to happen in
# the fixture, which every one of these tests goes through. Without it you get
# an AssertionError traceback per test instead of a skip.
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for real PostgreSQL pharmacy tests",
)


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    if not TEST_DATABASE_URL:
        pytest.skip("needs real PostgreSQL — run `make test-pg` from the repo root")
    test_engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def pharmacy_seed(db_session: AsyncSession) -> dict[str, uuid.UUID]:
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    pharmacist_id = uuid.uuid4()
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    visit_id = uuid.uuid4()
    encounter_id = uuid.uuid4()
    prescription_id = uuid.uuid4()
    prescription_item_id = uuid.uuid4()
    medicine_id = uuid.uuid4()
    location_id = uuid.uuid4()
    early_batch_id = uuid.uuid4()
    late_batch_id = uuid.uuid4()

    await db_session.execute(text("""
        INSERT INTO facilities (id, code, name, state_code, timezone)
        VALUES (:id, :code, 'Pharmacy Test Facility', 'TS', 'Asia/Kolkata')
    """), {"id": facility_id, "code": f"PHT{uuid.uuid4().hex[:8]}"})
    await db_session.execute(text("""
        INSERT INTO departments (id, name, code, facility_id)
        VALUES (:id, 'Pharmacy Test', :code, :facility_id)
    """), {"id": department_id, "code": f"PH{uuid.uuid4().hex[:6]}", "facility_id": facility_id})
    for user_id, username in ((pharmacist_id, "pharmacist"), (doctor_id, "doctor")):
        await db_session.execute(text("""
            INSERT INTO users (id, keycloak_sub, username, full_name, facility_id, department_id)
            VALUES (:id, :sub, :username, :full_name, :facility_id, :department_id)
        """), {
            "id": user_id, "sub": f"pharmacy-test-{user_id}", "username": f"{username}-{uuid.uuid4().hex[:8]}",
            "full_name": username.title(), "facility_id": facility_id, "department_id": department_id,
        })
    await db_session.execute(text("""
        INSERT INTO patients
            (id, uhid, full_name, sex, age_years, identity_path, facility_id, created_by)
        VALUES (:id, :uhid, 'Pharmacy Patient', 'unknown', 30, 'demographics_only', :facility_id, :created_by)
    """), {"id": patient_id, "uhid": f"UH{uuid.uuid4().hex[:10]}", "facility_id": facility_id, "created_by": doctor_id})
    await db_session.execute(text("""
        INSERT INTO visits
            (id, visit_number, patient_id, facility_id, department_id, visit_type, visit_date, created_by)
        VALUES (:id, :number, :patient_id, :facility_id, :department_id, 'opd', now(), :created_by)
    """), {"id": visit_id, "number": f"PV-{uuid.uuid4().hex[:10]}", "patient_id": patient_id,
             "facility_id": facility_id, "department_id": department_id, "created_by": doctor_id})
    await db_session.execute(text("""
        INSERT INTO encounters (id, visit_id, facility_id, provider_user_id, encounter_type, created_by)
        VALUES (:id, :visit_id, :facility_id, :provider, 'consultation', :created_by)
    """), {"id": encounter_id, "visit_id": visit_id, "facility_id": facility_id, "provider": doctor_id, "created_by": doctor_id})
    await db_session.execute(text("""
        INSERT INTO prescriptions
            (id, encounter_id, facility_id, patient_id, created_by)
        VALUES (:id, :encounter_id, :facility_id, :patient_id, :created_by)
    """), {"id": prescription_id, "encounter_id": encounter_id, "facility_id": facility_id,
             "patient_id": patient_id, "created_by": doctor_id})
    await db_session.execute(text("""
        INSERT INTO inventory_items (id, name, generic_name, strength, form, item_type)
        VALUES (:id, 'Test Paracetamol', 'Paracetamol', '500mg', 'tablet', 'medicine')
    """), {"id": medicine_id})
    await db_session.execute(text("""
        INSERT INTO prescription_items (id, prescription_id, medicine_item_id, medicine_name)
        VALUES (:id, :prescription_id, :medicine_id, 'Test Paracetamol')
    """), {"id": prescription_item_id, "prescription_id": prescription_id, "medicine_id": medicine_id})
    await db_session.execute(text("""
        INSERT INTO stock_locations (id, name, location_type, facility_id)
        VALUES (:id, 'Test Pharmacy', 'pharmacy', :facility_id)
    """), {"id": location_id, "facility_id": facility_id})
    await db_session.execute(text("""
        INSERT INTO inventory_batches
            (id, item_id, batch_number, expiry_date, quantity, stock_location_id)
        VALUES
            (:early, :item, 'EARLY', :early_expiry, 6, :location),
            (:late, :item, 'LATE', :late_expiry, 20, :location)
    """), {"early": early_batch_id, "late": late_batch_id, "item": medicine_id,
             "early_expiry": date.today() + timedelta(days=10),
             "late_expiry": date.today() + timedelta(days=100), "location": location_id})
    await db_session.flush()
    return {
        "facility_id": facility_id, "department_id": department_id, "pharmacist_id": pharmacist_id,
        "doctor_id": doctor_id, "patient_id": patient_id, "encounter_id": encounter_id,
        "prescription_id": prescription_id, "prescription_item_id": prescription_item_id,
        "medicine_id": medicine_id, "early_batch_id": early_batch_id, "late_batch_id": late_batch_id,
    }


@pytest_asyncio.fixture
async def inventory_seed(db_session: AsyncSession, pharmacy_seed: dict) -> dict:
    """Extra seed data for B6-W5-01: GRN, indent, adjustment tests.
    Reuses pharmacy_seed's facility/department/medicine; adds a supplier,
    a stock location, an HOD user, and a second pharmacist for dual sign-off.
    """
    supplier_id = uuid.uuid4()
    location_id = uuid.uuid4()
    hod_id = uuid.uuid4()
    second_pharmacist_id = uuid.uuid4()
    other_department_id = uuid.uuid4()
    other_hod_id = uuid.uuid4()

    await db_session.execute(text("""
        INSERT INTO suppliers (id, facility_id, name)
        VALUES (:id, :facility_id, 'Test Supplier')
    """), {"id": supplier_id, "facility_id": pharmacy_seed["facility_id"]})

    await db_session.execute(text("""
        INSERT INTO stock_locations (id, name, location_type, facility_id)
        VALUES (:id, 'Test GRN Store', 'central', :facility_id)
    """), {"id": location_id, "facility_id": pharmacy_seed["facility_id"]})

    await db_session.execute(text("""
        INSERT INTO users (id, keycloak_sub, username, full_name, facility_id, department_id)
        VALUES (:id, :sub, :username, 'HOD User', :facility_id, :department_id)
    """), {
        "id": hod_id, "sub": f"inventory-test-hod-{hod_id}",
        "username": f"hod-{uuid.uuid4().hex[:8]}",
        "facility_id": pharmacy_seed["facility_id"], "department_id": pharmacy_seed["department_id"],
    })

    await db_session.execute(text("""
        INSERT INTO users (id, keycloak_sub, username, full_name, facility_id, department_id)
        VALUES (:id, :sub, :username, 'Second Pharmacist', :facility_id, :department_id)
    """), {
        "id": second_pharmacist_id, "sub": f"inventory-test-pharm2-{second_pharmacist_id}",
        "username": f"pharm2-{uuid.uuid4().hex[:8]}",
        "facility_id": pharmacy_seed["facility_id"], "department_id": pharmacy_seed["department_id"],
    })

    # A second department + its own HOD, to prove cross-department approval is rejected.
    await db_session.execute(text("""
        INSERT INTO departments (id, name, code, facility_id)
        VALUES (:id, 'Other Dept', :code, :facility_id)
    """), {"id": other_department_id, "code": f"OD{uuid.uuid4().hex[:6]}",
             "facility_id": pharmacy_seed["facility_id"]})
    await db_session.execute(text("""
        INSERT INTO users (id, keycloak_sub, username, full_name, facility_id, department_id)
        VALUES (:id, :sub, :username, 'Other HOD', :facility_id, :department_id)
    """), {
        "id": other_hod_id, "sub": f"inventory-test-otherhod-{other_hod_id}",
        "username": f"otherhod-{uuid.uuid4().hex[:8]}",
        "facility_id": pharmacy_seed["facility_id"], "department_id": other_department_id,
    })

    await db_session.flush()
    return {
        **pharmacy_seed,
        "supplier_id": supplier_id,
        "location_id": location_id,
        "hod_id": hod_id,
        "second_pharmacist_id": second_pharmacist_id,
        "other_department_id": other_department_id,
        "other_hod_id": other_hod_id,
    }
