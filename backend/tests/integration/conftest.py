"""tests/integration/conftest.py

Auth overrides + facility/department/patient seeding for the #243
integration (journey) tests.

No conftest.py exists yet for opd/encounters/orders/billing individually
(unlike pathology/radiology), so this file is the first one covering
them for HTTP-level testing. Pattern copied deliberately from
tests/pathology/conftest.py and tests/radiology/conftest.py (client_as
fixture, dependency overrides on get_current_user / get_current_db_user
/ get_db) so it stays consistent with the two existing integration-shaped
suites your lead referenced (tests/billing/test_billing_flows.py and
tests/pharmacy/test_pharmacy_integration.py) — those two call service
functions directly against real Postgres; this one drives the actual
HTTP endpoints, because a "journey" test needs to exercise the same path
a real client (frontend / mobile app) would.

FIXED (not random) sub/id values, same convention as tests/_lab_seed.py's
own docstring: "Fixed ids so repeated runs reuse the same rows instead of
accumulating." The original version of this file used uuid.uuid4() for
each AuthUser's sub, which changes every test run — so ON CONFLICT (id) DO
NOTHING never matched the previous run's row (different id each time), and
the insert instead collided on the separately-unique username column.
Fixed subs make uid stable across runs, so reruns are truly idempotent.

KNOWN INCONSISTENCY WORTH FLAGGING TO THE LEAD:
- app/opd/router.py's create_visit passes created_by=current_db_user.id
  into service.create_visit() explicitly, ignoring payload.created_by.
- app/encounters/router.py's create_encounter and app/orders/router.py's
  create_order do NOT do this — they forward payload straight through,
  so payload.created_by / payload.provider_user_id are trusted as-is,
  contrary to what both routers' module docstrings claim ("created_by
  ... come[s] from current_db_user, never the request body"). This test
  file works around it by always setting those fields to the acting
  user's id, but the routers themselves look like they have a real gap.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.main import app
from tests._lab_seed import TEST_DATABASE_URL

TEST_FACILITY_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f2")
TEST_DEPARTMENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
TEST_PATIENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e3")

# Fixed subs (not uuid4()) so uid derived below is stable across test runs —
# required for ON CONFLICT (id) DO NOTHING to actually match prior rows.
RECEPTIONIST = AuthUser(sub="opdj-sub-receptionist-0001", username="opdj-reception1", roles=["receptionist"])
DOCTOR = AuthUser(sub="opdj-sub-doctor-0001", username="opdj-doc1", roles=["doctor"])
NURSE = AuthUser(sub="opdj-sub-nurse-0001", username="opdj-nurse1", roles=["nurse"])
LAB_TECH = AuthUser(sub="opdj-sub-labtech-0001", username="opdj-tech1", roles=["lab_tech"])
PATHOLOGIST = AuthUser(sub="opdj-sub-pathologist-0001", username="opdj-patho1", roles=["pathologist"])
SUPERVISOR = AuthUser(sub="opdj-sub-supervisor-0001", username="opdj-super1", roles=["supervisor"])
ADMIN = AuthUser(sub="opdj-sub-admin-0001", username="opdj-admin1", roles=["admin"])

ALL_TEST_USERS = [RECEPTIONIST, DOCTOR, NURSE, LAB_TECH, PATHOLOGIST, SUPERVISOR, ADMIN]


def _db_user_for(user: AuthUser) -> DbUser:
    return DbUser(
        id=uuid.uuid5(uuid.NAMESPACE_OID, user.sub),
        keycloak_sub=user.sub,
        username=user.username,
        facility_id=TEST_FACILITY_ID,
        roles=user.roles,
    )


_test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


async def _test_get_db():
    async with _TestSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
def client_as():
    with TestClient(app) as client:
        def _make(user: AuthUser) -> TestClient:
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_current_db_user] = lambda: _db_user_for(user)
            app.dependency_overrides[get_db] = _test_get_db
            return client

        yield _make

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_db_user, None)
    app.dependency_overrides.pop(get_db, None)


async def _seed() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(
                "INSERT INTO facilities (id, code, name, state_code, timezone) "
                "VALUES (:id, 'OPDJRN', 'OPD Journey Test Facility', 'DL', 'Asia/Kolkata') "
                "ON CONFLICT (id) DO NOTHING"), {"id": TEST_FACILITY_ID})

            await conn.execute(sa.text(
                "INSERT INTO departments (id, code, name, facility_id) "
                "VALUES (:id, 'OPDJ', 'OPD Journey Test Dept', :fac) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": TEST_DEPARTMENT_ID, "fac": TEST_FACILITY_ID})

            for user in ALL_TEST_USERS:
                uid = uuid.uuid5(uuid.NAMESPACE_OID, user.sub)
                await conn.execute(sa.text(
                    "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                    "VALUES (:id, :sub, :username, 'OPD Journey Test User', :fac) "
                    "ON CONFLICT (id) DO NOTHING"),
                    {"id": uid, "sub": user.sub, "username": user.username, "fac": TEST_FACILITY_ID})

            creator = uuid.uuid5(uuid.NAMESPACE_OID, RECEPTIONIST.sub)

            # The registration tariff (#389). POST /visits now creates the visit's
            # invoice in the same transaction and prices its fee line from
            # charge_master, so a facility with no active REGISTRATION row cannot
            # register patients — it 409s with registration_tariff_not_configured.
            # That is deliberate: the alternative was zero-rupee invoices that look
            # legitimate. Every facility seed needs this row, including the demo one.
            await conn.execute(sa.text(
                "INSERT INTO charge_master (id, facility_id, charge_code, description, "
                "  charge_category, unit_price, effective_from, is_active, created_by) "
                "VALUES (:id, :fac, 'REGISTRATION', 'OPD registration fee', "
                "        'registration', 200.00, DATE '2020-01-01', true, :by) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": uuid.uuid5(uuid.NAMESPACE_OID, "charge-master-registration"),
                 "fac": TEST_FACILITY_ID, "by": creator})

            await conn.execute(sa.text(
                "INSERT INTO patients (id, full_name, sex, identity_path, facility_id, "
                " created_by, age_years, uhid) "
                "VALUES (:id, 'OPD Journey Test Patient', 'other', 'demographics_only', :fac, "
                "        :by, 40, :uhid) "
                "ON CONFLICT (id) DO NOTHING"),
                {"id": TEST_PATIENT_ID, "fac": TEST_FACILITY_ID, "by": creator,
                 "uhid": f"IN-DL-OPDJ-2026-{str(TEST_PATIENT_ID)[:6]}"})
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def seeded_patient_id() -> str:
    import asyncio
    asyncio.run(_seed())
    return str(TEST_PATIENT_ID)
