"""
Shared fixtures for backend/tests/consent/.

Repo path: backend/tests/consent/conftest.py

Deliberately mirrors backend/tests/audit/conftest.py's structure and
reasoning as closely as this module's tables allow, rather than
inventing a second convention:

  - function-scoped `engine` (not session-scoped) — pytest-asyncio
    gives each test its own event loop; a shared engine's pool would
    hold connections from a closed loop across test boundaries, which
    is the same "Event loop is closed" failure audit's conftest
    documents. Costs a bit of per-test connection setup, never crosses
    a loop boundary.
  - real commits via `engine.begin()`, not a wrapping
    transaction-per-test rolled back at teardown — this module's
    tests need to observe REAL trigger behavior across statement
    boundaries (the freeze trigger, the withdrawal status-flip, the
    append-only block on data_access_log), same reasoning as audit's
    chain_seq-gap tests.
  - Windows asyncpg event-loop-policy fix, copied verbatim — same repo,
    same failure mode, no reason to solve it twice differently.

WHAT'S DIFFERENT FROM tests/audit/conftest.py, AND WHY
-----------------------------------------------------------
- No `ScratchAuditedThing`-equivalent — this module has no auto-audit
  opt-in mechanism to exercise; consent_records/consent_withdrawals/
  data_access_log are tested directly via raw SQL against the real
  tables, same as test_audit_logs_db.py does for audit_logs.
- `user_id` fixture is NEW here (audit's conftest never needed one) —
  consent_records.created_by, data_access_log.user_id, and
  break_glass_grants.granted_to_user_id are all NOT NULL FKs to
  users.id, so every consent test needs a real user row, not just a
  real facility row.
- Teardown does NOT attempt to delete consent_records / consent_withdrawals
  / break_glass_grants / data_access_log rows created during a test,
  same philosophy as audit's facility_id fixture: data_access_log is
  append-only (DELETE is trigger-blocked, same as audit_logs), and
  consent_records has FK-RESTRICT dependents (consent_withdrawals,
  break_glass_grants reference it) that would need deleting in a
  specific order first. Rather than reimplement fragile teardown
  ordering for a throwaway database, test rows accumulate in
  healthdoc_test with obviously-tagged names/codes — same as audit's
  approach, see its facility_id docstring. Periodically drop/recreate
  healthdoc_test instead of trying to clean individual rows out of
  tables that are specifically designed to resist that.
- users rows ARE left behind for the same reason (consent_records.created_by
  RESTRICTs deletion) — tagged with a `consent-test-` prefix in
  keycloak_sub so they're identifiable if anyone audits the throwaway DB.

facilities.timezone note: same gap audit's conftest already documented
(§3 0002 requires it, the merged 0002 doesn't have it) — this file's
facility_id fixture only inserts columns that actually exist today,
same reasoning, not duplicating the flag to whoever owns 0002.
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
    """Function-scoped — see module docstring for why."""
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """One throwaway facilities row per test. See module docstring for
    the timezone gap and the no-teardown-delete reasoning (mirrors
    tests/audit/conftest.py's facility_id fixture)."""
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'Consent Test Facility', 'RJ')
                """
            ),
            {"id": fid, "code": f"CNST{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    # No delete — see module docstring. facilities is also referenced
    # by audit_logs (ON DELETE RESTRICT) from any prior test run in
    # this shared throwaway DB, so it usually couldn't be deleted even
    # if this module's own tables allowed it.


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, facility_id: uuid.UUID) -> AsyncGenerator[uuid.UUID, None]:
    """One throwaway users row per test, tied to facility_id above."""
    uid = uuid.uuid4()
    sub = f"consent-test-{uid}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)
                VALUES (:id, :sub, :sub, 'Consent Test User', :facility_id)
                """
            ),
            {"id": uid, "sub": sub, "facility_id": facility_id},
        )
    yield uid
    # No delete — consent_records.created_by and friends may RESTRICT it
    # by the time a test finishes. See module docstring.
