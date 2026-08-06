"""
Shared fixtures for the billing test suite.

IMPORTANT — adapt before merging:
This repo is a skeleton and no shared backend/tests/conftest.py exists
yet (no other dev has pushed). These fixtures are self-contained on
purpose so this file runs standalone today. Once a repo-wide conftest.py
exists (engine/session fixtures, a migrated test DB, factory helpers for
facilities/users/patients/visits), DELETE the duplicated fixtures below
and import the shared ones instead — the test bodies in
test_billing_*.py should not need to change, only these fixtures.

WHY REAL POSTGRES, NOT SQLITE/MOCKS:
Every test in this module exercises a real DB trigger
(trg_invoices_freeze, trg_invoice_items_freeze, trg_payments_block,
trg_refunds_block) or a real constraint (CHECK, UNIQUE,
FOR UPDATE row locking). None of that exists in SQLite or in a mocked
session — this suite is only meaningful against Postgres. Point
TEST_DATABASE_URL at a throwaway Postgres database (docker compose's
`db` service with a different database name is fine) before running.

ISOLATION:
Each test runs inside its own transaction that's rolled back at the end
(session fixture below), so tests don't need to clean up after
themselves and can run in any order / in parallel-per-worker. Rollback
also means trg_*_freeze / trg_*_block triggers firing INSIDE a test
(the whole point of several tests here) never actually corrupts state
for the next test.
WINDOWS NOTE (from the audit module's own debugging log — same repo,
same problem, already solved once): a session-scoped AsyncEngine
fixture reused connections across pytest-asyncio's per-test event
loops on Windows, producing `RuntimeError: Event loop is closed` /
`'NoneType' object has no attribute 'send'`. Fixed there by (a) making
the engine fixture function-scoped instead of session-scoped, and
(b) forcing WindowsSelectorEventLoopPolicy. Both applied below from the
start, so this suite doesn't have to rediscover the same bug.

KNOWN RISK — facilities.timezone: the consent module's own testing
found that the REAL migration 0002 on this repo's branches has, at
least once, been missing `facilities.timezone` despite the schema doc
requiring it (worked around there by dropping it from the test INSERT
and flagging separately — not that module's bug to fix). Billing's
service.py genuinely depends on this column
(_facility_business_date/_facility_timezone read it directly) — if
seed_facility() below fails with
`column "timezone" of relation "facilities" does not exist`, that is
the SAME pre-existing gap, not a bug in this test file or in billing.
Don't silently drop the column from the INSERT to make tests pass —
that would hide a real production bug (billing's timezone-aware MIS
queries would then fail for real, not just in tests). Flag it to
whoever owns migration 0002 instead, the same way the consent PR did.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if sys.platform == "win32":
    # Same fix as the audit module's test suite — see module docstring.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc_test",
)


@pytest_asyncio.fixture
async def engine():
    """
    Function-scoped (NOT session-scoped) on purpose — see the Windows
    note in this module's docstring. A fresh engine per test is slower
    but avoids a connection outliving the event loop pytest-asyncio
    tears down between tests. Assumes `alembic upgrade head` (or the
    scratch/run_0014_standalone.py workaround) has already been run
    against TEST_DATABASE_URL.
    """
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    """
    One AsyncSession per test, wrapping everything in an outer
    transaction that's rolled back on teardown — see module docstring.
    Uses SAVEPOINTs internally (join_transaction_mode="create_savepoint")
    so code under test (e.g. service._insert_invoice_item's own
    begin_nested()) can freely open its own nested transactions without
    interfering with the outer rollback boundary.
    """
    connection = await engine.connect()
    outer_tx = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await outer_tx.rollback()
        await connection.close()


# ---------------------------------------------------------------------
# Minimal seed helpers — raw SQL, deliberately not importing other
# modules' ORM models (facilities/users/patients/visits), same
# cross-module convention service.py itself uses (bare sa.table()
# projections) to avoid a hard import dependency between test modules
# and modules owned by other devs who haven't pushed yet.
# ---------------------------------------------------------------------


async def seed_facility(db: AsyncSession, *, timezone_name: str = "Asia/Kolkata", code: str | None = None) -> uuid.UUID:
    facility_id = uuid.uuid4()
    code = code or f"TST{str(facility_id)[:5].upper()}"
    await db.execute(
        sa.text(
            "INSERT INTO facilities (id, code, name, timezone) "
            "VALUES (:id, :code, :name, :tz)"
        ),
        {"id": facility_id, "code": code, "name": f"Test Facility {code}", "tz": timezone_name},
    )
    return facility_id


async def seed_user(db: AsyncSession, *, facility_id: uuid.UUID, keycloak_sub: str | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    keycloak_sub = keycloak_sub or f"sub-{user_id}"
    await db.execute(
        sa.text(
            "INSERT INTO users (id, facility_id, keycloak_sub, username) "
            "VALUES (:id, :facility_id, :sub, :username)"
        ),
        {"id": user_id, "facility_id": facility_id, "sub": keycloak_sub, "username": keycloak_sub},
    )
    return user_id


async def seed_patient(db: AsyncSession, *, facility_id: uuid.UUID) -> uuid.UUID:
    patient_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO patients (id, facility_id, status) "
            "VALUES (:id, :facility_id, 'active')"
        ),
        {"id": patient_id, "facility_id": facility_id},
    )
    return patient_id


async def seed_visit(db: AsyncSession, *, facility_id: uuid.UUID, patient_id: uuid.UUID) -> uuid.UUID:
    visit_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO visits (id, facility_id, patient_id, visit_type, status) "
            "VALUES (:id, :facility_id, :patient_id, 'opd', 'registered')"
        ),
        {"id": visit_id, "facility_id": facility_id, "patient_id": patient_id},
    )
    return visit_id


async def seed_draft_invoice(
    db: AsyncSession, *, facility_id: uuid.UUID, patient_id: uuid.UUID, visit_id: uuid.UUID,
    created_by: uuid.UUID, gross_amount: str = "0", net_amount: str = "0",
) -> uuid.UUID:
    """Mirrors registration's real behaviour (schema doc §3 0014: invoices
    are created at registration, not by the billing endpoints)."""
    invoice_id = uuid.uuid4()
    invoice_number = f"INV-TST-{str(invoice_id)[:8].upper()}"
    await db.execute(
        sa.text(
            "INSERT INTO invoices "
            "(id, invoice_number, visit_id, patient_id, facility_id, status, "
            " gross_amount, net_amount, created_by) "
            "VALUES (:id, :num, :visit_id, :patient_id, :facility_id, 'draft', "
            " :gross, :net, :created_by)"
        ),
        {
            "id": invoice_id, "num": invoice_number, "visit_id": visit_id,
            "patient_id": patient_id, "facility_id": facility_id,
            "gross": gross_amount, "net": net_amount, "created_by": created_by,
        },
    )
    return invoice_id


@pytest_asyncio.fixture
async def facility(db: AsyncSession) -> uuid.UUID:
    return await seed_facility(db)


@pytest_asyncio.fixture
async def other_facility(db: AsyncSession) -> uuid.UUID:
    """A second facility — used by the cross-facility MIS scoping test."""
    return await seed_facility(db)


@pytest_asyncio.fixture
async def user(db: AsyncSession, facility: uuid.UUID) -> uuid.UUID:
    return await seed_user(db, facility_id=facility)


@pytest_asyncio.fixture
async def patient(db: AsyncSession, facility: uuid.UUID) -> uuid.UUID:
    return await seed_patient(db, facility_id=facility)


@pytest_asyncio.fixture
async def visit(db: AsyncSession, facility: uuid.UUID, patient: uuid.UUID) -> uuid.UUID:
    return await seed_visit(db, facility_id=facility, patient_id=patient)


@pytest_asyncio.fixture
async def draft_invoice(
    db: AsyncSession, facility: uuid.UUID, patient: uuid.UUID, visit: uuid.UUID, user: uuid.UUID,
) -> uuid.UUID:
    return await seed_draft_invoice(
        db, facility_id=facility, patient_id=patient, visit_id=visit, created_by=user,
    )
