"""
Shared fixtures for backend/tests/files/.

Repo path: backend/tests/files/conftest.py

Mirrors backend/tests/audit/conftest.py's conventions (TEST_DATABASE_URL,
function-scoped `engine`, WindowsSelectorEventLoopPolicy, facility fixture
naming/shape) so both suites point at the same real test database and
look the same to anyone reading both. See that file's docstring for the
reasoning behind each of these choices — not re-litigated here.

No divergence from audit's conftest any more: `engine` assumes migrations
are already applied externally (`alembic upgrade head`), same as audit's,
because 0019 is now a merged migration in a runnable chain.

It used to do more. While 0019 was parked, this fixture applied and reverted
it per test through an isolated MigrationContext, and stubbed the tables it
references that hadn't merged yet. All of that is gone — consent_records
(0004), patients (0006) and order_external_results (0008) are real, 0019
itself is real, and re-applying a migration alembic has already run raises
DuplicateTableError.

Worth remembering why the scaffolding existed, though: each of those three
tables broke this file on the day its migration merged, because a stub-era
CREATE or INSERT stopped matching reality. If you ever stub a table here
again, decide at runtime whether it exists rather than assuming.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if sys.platform == "win32":
    # Matches tests/audit/conftest.py exactly — must run at import time,
    # before pytest-asyncio creates any event loop, or asyncpg's
    # connection cleanup is unreliable under the default ProactorEventLoop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportDeprecated]

# Same env var + same default as tests/audit/conftest.py, so both
# suites hit the same disposable test database when run together. This
# was previously hardcoded to the `healthdoc` dev database by mistake —
# real bug, not a style nit: tests were writing scratch rows into the
# actual dev DB instead of the disposable healthdoc_test one.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc_test",
)


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Function-scoped, matching tests/audit/conftest.py's `engine`
    fixture name and pool_pre_ping=True — see that file's docstring for
    why session-scoped breaks under pytest-asyncio's per-test event loop.

    This used to apply and revert 0019 per test through an isolated
    MigrationContext, because 0019 was parked and `alembic upgrade head`
    could not reach it. 0019 is in the chain now, so the migration runs
    once as part of the normal upgrade and applying it again here raised
    DuplicateTableError on every test. Simplified to match audit's, which
    is what the old docstring said should happen "once the chain is
    unbroken".
    """
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


async def _required_columns(conn, table_name: str) -> list[dict]:
    """Introspect a table's NOT NULL columns that have no server default.

    Kept as a fallback for tables this module doesn't have a proven real
    INSERT for (currently just `users` — see the user_id fixture below).
    Prefer a real, already-proven INSERT over this wherever one exists;
    this is the "we genuinely don't know the schema" safety net, not the
    first choice. See seed_row()'s docstring for the full reasoning.
    """
    result = await conn.execute(
        sa.text(
            """
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = :t
              AND is_nullable = 'NO'
              AND column_default IS NULL
            """
        ),
        {"t": table_name},
    )
    return [dict(row._mapping) for row in result]


def _placeholder_for(data_type: str, column_name: str, max_length: int | None = None):
    """A throwaway value of the right type (and, for text, the right
    length) — good enough to satisfy a NOT NULL constraint on a column
    the test doesn't actually care about.
    """
    if data_type == "uuid":
        return uuid.uuid4()
    if data_type == "boolean":
        return True
    if data_type in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return 0
    if data_type in ("timestamp with time zone", "timestamp without time zone"):
        return datetime.now(timezone.utc)
    if data_type == "date":
        return date.today()

    # text / character varying / anything else. Always built from a hex
    # UUID fragment so it's collision-safe against UNIQUE constraints —
    # but clamped to the column's real max_length instead of assuming
    # there's room for a descriptive "test_x_" prefix.
    token = uuid.uuid4().hex  # 32 hex chars
    descriptive = f"test_{column_name}_{token[:8]}"
    if max_length is None:
        return descriptive
    if max_length >= len(descriptive):
        return descriptive
    return token[:max_length]


async def seed_row(conn, table_name: str, **overrides) -> dict:
    """Insert one row into `table_name`, auto-filling any NOT NULL column
    without a default that `overrides` didn't already specify.

    This is the fallback for tables with no proven real INSERT to copy —
    right now, just `users`. `facilities` used to go through this too,
    but tests/audit/conftest.py already has a real, 11/11-passing INSERT
    for it (id, code, name, state_code) — copying proven code beats
    guessing at a schema generically, so facility_id below uses that
    directly instead of this function. Keep that precedence if either
    fixture changes: real proof > generic introspection.
    """
    row = dict(overrides)
    for col in await _required_columns(conn, table_name):
        name = col["column_name"]
        if name not in row:
            row[name] = _placeholder_for(col["data_type"], name, col["character_maximum_length"])

    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row.keys())
    await conn.execute(sa.text(f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"), row)
    return row


@pytest_asyncio.fixture
async def facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """One throwaway facilities row.

    Copied directly from tests/audit/conftest.py's facility_id fixture —
    same real column set (id, code, name, state_code), same 'FCIL' +
    hex-suffix code convention, same accumulate-instead-of-delete
    teardown discipline. See that file's docstring for why teardown
    doesn't DELETE: anything that later points at this row (files ->
    facilities is ON DELETE RESTRICT, same as audit_logs -> facilities)
    would block it anyway, so cleanup is "drop/recreate the whole test
    DB periodically," not per-row deletes.
    """
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'Files Test Facility', 'RJ')
                """
            ),
            {"id": fid, "code": f"FCIL{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    # No DELETE — see docstring.


@pytest_asyncio.fixture
async def second_facility_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """A second facility — for cross-facility scoping tests."""
    fid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO facilities (id, code, name, state_code)
                VALUES (:id, :code, 'Files Test Facility 2', 'RJ')
                """
            ),
            {"id": fid, "code": f"FCIL{uuid.uuid4().hex[:6]}"},
        )
    yield fid
    # No DELETE — see facility_id's docstring.


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, facility_id: uuid.UUID) -> uuid.UUID:
    """One throwaway users row, scoped to facility_id.

    Real schema confirmed (\\d users, migration 0002): keycloak_sub
    VARCHAR(64) UNIQUE NOT NULL, username VARCHAR(100) UNIQUE NOT NULL,
    full_name TEXT NOT NULL, facility_id UUID NOT NULL FK. Everything
    else (email, mobile, designation, employee_id, registration_number,
    qualification) is nullable, and UNIQUE(facility_id, employee_id)
    doesn't bite since employee_id is left NULL here. Real literal
    INSERT now, same as facility_id below — seed_row()'s generic
    introspection was the honest fallback while this schema was
    unconfirmed; now that it's proven, copy it directly instead.

    facility_id is passed explicitly (not auto-filled) since it must
    point at a facility that actually exists — this fixture's own
    facility_id dependency guarantees that.
    """
    uid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO users (id, keycloak_sub, username, full_name, facility_id)
                VALUES (:id, :sub, :username, 'Files Test User', :facility_id)
                """
            ),
            {
                "id": uid,
                "sub": str(uid),
                "username": f"filetest_{uuid.uuid4().hex[:12]}",
                "facility_id": facility_id,
            },
        )
    return uid


async def seed_file(conn, facility_id: uuid.UUID, user_id: uuid.UUID, **overrides) -> uuid.UUID:
    """Insert one files row inside the caller's transaction, return its id.

    Not a fixture — a plain helper, since individual tests need to seed
    files with different overrides (e.g. missing sha256) inside their own
    `pytest.raises` block rather than at fixture setup time.
    """
    file_id = uuid.uuid4()
    row = {
        "id": file_id,
        "bucket": "hd-files",
        "object_key": f"test/{file_id}.pdf",
        "sha256": "a" * 64,
        "facility_id": facility_id,
        "uploaded_by": user_id,
        **overrides,
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row.keys())
    await conn.execute(sa.text(f"INSERT INTO files ({cols}) VALUES ({placeholders})"), row)
    return file_id
