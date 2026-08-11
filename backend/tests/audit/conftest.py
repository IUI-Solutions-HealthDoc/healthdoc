"""
Shared fixtures for backend/tests/audit/.

Repo path: backend/tests/audit/conftest.py

These tests run against a REAL Postgres database with migrations already
applied (alembic upgrade head) -- the behavior under test is trigger and
partitioning logic that Postgres implements, not something an ORM-level
mock or sqlite could faithfully stand in for. See the "Running tests"
section of the PR description / README for how to point this at a local
or CI database.

Deliberately NOT using a single wrapping transaction-per-test with a
rollback at the end (the common "fast test isolation" pattern) for the
gap tests specifically -- those tests need to observe the effect of a
REAL commit vs a REAL rollback on audit_counters, so they manage their
own transactions explicitly and clean up with DELETEs instead.

Windows note: asyncpg's connection cleanup is unreliable under the
default ProactorEventLoop (manifests as "Event loop is closed" /
"'NoneType' object has no attribute 'send'" during pool teardown) --
force the selector policy below. This must run at import time, before
pytest-asyncio creates any event loop.
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
    # Deprecated as a *policy-based* API starting Python 3.14 (removal in
    # 3.16) in favor of explicit loop factories -- irrelevant on this
    # repo's pinned 3.12, but silenced explicitly rather than ignored so
    # it doesn't get missed when the repo eventually upgrades past 3.13.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportDeprecated]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/healthdoc_test",
)


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Deliberately function-scoped (one engine per test), NOT session-
    scoped. pytest-asyncio gives each test its own event loop by
    default; a session-scoped engine's connection pool would then hold
    connections created in test A's loop and try to reuse them in test
    B's already-closed loop, which is exactly the "Event loop is
    closed" crash. A fresh engine/pool per test costs a bit of
    connection-setup time but never crosses a loop boundary.
    """
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """
    One throwaway facilities row per test.

    NOTE: facilities.timezone is required by the schema doc (§3 0002)
    but is NOT present in this branch's actual 0002 migration as of
    2026-08 -- confirmed via `\\d facilities` against a freshly-migrated
    healthdoc_test (alembic_version = 0003, so this isn't a stale-DB
    artifact). That's a real gap in 0002, already merged to staging --
    not something the audit module owns or should silently patch over
    by inserting a value the real schema doesn't have room for. Flagged
    separately to whoever owns 0002; this INSERT only uses columns that
    actually exist today so the audit module's own tests aren't blocked
    on someone else's migration. Add `timezone` back here once 0002 is
    fixed, to keep this fixture honest about what a real facilities row
    looks like.

    NOT deleting facilities or audit_logs rows in teardown -- and this
    is deliberate, not an oversight. audit_logs blocks ALL deletes (the
    append-only trigger under test); trying to clean it up here means
    fighting the exact guarantee this migration exists to provide, and
    was actually crashing teardown for every test that inserted an
    audit row. facilities -> audit_logs is also ON DELETE RESTRICT, so
    even the facilities row can't go once anything points at it. Test
    facilities accumulate in healthdoc_test (a throwaway database) with
    obviously-tagged codes (AUDT...) -- periodically drop/recreate the
    whole database instead of trying to delete individual rows out of
    tables that are specifically designed not to allow that.
    """
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'Audit Test Facility', 'RJ')
                """
            ),
            {"id": fid, "code": f"AUDT{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_counters WHERE facility_id = :id"), {"id": fid})


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, facility_id: uuid.UUID) -> AsyncGenerator[uuid.UUID, None]:
    """One throwaway users row, scoped to facility_id — needed for the
    query-API tests (audit_logs.user_id FK, CurrentDbUser-shaped facility
    scoping). Not needed by the existing trigger/partition tests in this
    package, which is why it wasn't here before. Same no-DELETE reasoning
    as facility_id above — users is also referenced by ON DELETE RESTRICT
    from audit_logs.user_id."""
    uid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)
                VALUES (:id, :sub, :sub, 'Audit Test User', :facility_id)
                """
            ),
            {"id": uid, "sub": f"audit-test-{uid}", "facility_id": facility_id},
        )
    yield uid
    # No delete — see facility_id's docstring.


@pytest_asyncio.fixture
async def second_facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """A second facility, for the offline-sync independence test. See facility_id's docstring re: timezone and teardown."""
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'Audit Test Facility 2', 'RJ')
                """
            ),
            {"id": fid, "code": f"AUDT{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_counters WHERE facility_id = :id"), {"id": fid})


import uuid as _uuid  # noqa: E402  (kept near its only use below)

from sqlalchemy.dialects.postgresql import UUID  # noqa: E402
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402

from app.common.db import Base  # noqa: E402


class ScratchAuditedThing(Base):
    """
    Minimal, throwaway model that opts into listeners.py's auto-audit
    mechanism via __audit_resource_type__ / __audit_facility_id_field__,
    so tests can exercise the ORM-level (before_flush/after_flush) path
    without depending on a real domain module. Registered once at
    import time (not per-test) -- SQLAlchemy's mapper registry doesn't
    support clean re-registration, so re-declaring this class inside a
    fixture would break on the second test that used it.
    """

    __tablename__ = "scratch_audited_things"
    __audit_resource_type__ = "scratch_audited_things"
    __audit_facility_id_field__ = "facility_id"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    facility_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(nullable=False)


@pytest_asyncio.fixture
async def scratch_audited_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """
    Creates/drops the physical table backing ScratchAuditedThing via raw
    DDL -- deliberately NOT an Alembic migration, since this table
    should never exist outside test runs.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scratch_audited_things (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    facility_id UUID NULL,
                    name TEXT NOT NULL
                )
                """
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS scratch_audited_things"))
