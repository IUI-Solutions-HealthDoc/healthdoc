"""
Shared fixtures for backend/tests/dpdp/.

Repo path: backend/tests/dpdp/conftest.py

Mirrors backend/tests/consent/conftest.py's conventions (TEST_DATABASE_URL,
function-scoped `engine`, WindowsSelectorEventLoopPolicy, no-teardown-delete
for FK-RESTRICT rows). Migration 0022a's own dependencies (facilities,
users, patients, consent_records) are all merged; `alembic upgrade head`
(or the equivalent bootstrap) is assumed already run against
TEST_DATABASE_URL for those, same assumption tests/audit and tests/consent
make. down_revision = "0022" (order_number_counters) may itself still be
mid-flight -- that's a chain-position concern for the real alembic CLI,
not for these tests, which apply 0022a's upgrade()/downgrade() directly.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportDeprecated]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/healthdoc_test",
)


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Function-scoped -- see tests/audit/conftest.py's docstring for why."""
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'DPDP Test Facility', 'RJ')
                """
            ),
            {"id": fid, "code": f"DPDP{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    # No delete -- see tests/audit/conftest.py's facility_id docstring.


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, facility_id: uuid.UUID) -> AsyncGenerator[uuid.UUID, None]:
    uid = uuid.uuid4()
    sub = f"dpdp-test-{uid}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)
                VALUES (:id, :sub, :sub, 'DPDP Test User', :facility_id)
                """
            ),
            {"id": uid, "sub": sub, "facility_id": facility_id},
        )
    yield uid


@pytest_asyncio.fixture
async def patient_id(engine: AsyncEngine, facility_id: uuid.UUID, user_id: uuid.UUID) -> AsyncGenerator[uuid.UUID, None]:
    pid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO patients (id, full_name, sex, identity_path, facility_id, "
                "created_by, age_years, uhid) "
                "VALUES (:id, 'DPDP Test Patient', 'other', 'demographics_only', :facility_id, "
                ":created_by, 30, :uhid)"
            ),
            {"id": pid, "facility_id": facility_id, "created_by": user_id, "uhid": f"UHID{pid.hex[:8]}"},
        )
    yield pid
