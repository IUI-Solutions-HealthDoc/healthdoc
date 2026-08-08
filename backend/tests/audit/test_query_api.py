"""
Tests for the audit query API's service layer (B7-W4-01).

Repo path: backend/tests/audit/test_query_api.py

Service-level, real Postgres — same convention as test_audit_logs_db.py
in this package. No FastAPI/HTTP layer here: this repo has no established
pattern yet for overriding auth dependencies in a router-level test (only
tests/conftest.py's bare `client` fixture exists, unused by any module so
far), so router.py's two endpoints stay thin wiring over service.py and
the actual filtering/pagination/CSV logic is verified here instead.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.audit import service

pytestmark = pytest.mark.asyncio


async def _insert_audit_row(engine: AsyncEngine, facility_id, **overrides):
    """Same helper as test_audit_logs_db.py — kept local rather than
    imported, matching this repo's convention of not sharing test helpers
    across files unless the duplication is actually painful."""
    columns = {
        "facility_id": facility_id,
        "action": "create",
        "resource_type": "test_resource",
        **overrides,
    }
    col_names = ", ".join(columns)
    placeholders = ", ".join(f":{k}" for k in columns)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                f"INSERT INTO audit_logs ({col_names}) VALUES ({placeholders}) "
                f"RETURNING id, created_at, chain_seq"
            ),
            columns,
        )
        return result.one()


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
def bind_export_to_test_engine(monkeypatch, session_factory):
    """stream_audit_logs_csv() opens its OWN app.common.db.SessionLocal
    (see service.py's module docstring for why) — that's the real app
    singleton, bound to settings.database_url (the dev DB) and to
    whichever event loop first used it, not TEST_DATABASE_URL / this
    test's per-test loop. Same fix as
    tests/consent/test_access_log.py's bind_access_log_to_test_engine:
    monkeypatch the module-level name the generator actually reads."""
    import app.audit.service as service_module

    monkeypatch.setattr(service_module, "SessionLocal", session_factory)


async def test_list_scopes_to_facility_id(
    engine: AsyncEngine, session_factory, facility_id, second_facility_id, user_id
):
    """The one filter that's never a query param — resolved server-side
    in router.py from CurrentDbUser.facility_id. A row in a DIFFERENT
    facility must never be visible, no matter what other filters match."""
    await _insert_audit_row(engine, facility_id, user_id=user_id)
    await _insert_audit_row(engine, second_facility_id)

    async with session_factory() as db:
        items, total = await service.list_audit_logs(db, facility_id=facility_id)

    assert total == 1
    assert all(str(i.facility_id) == str(facility_id) for i in items)


async def test_list_filters_by_user_id_patient_id_resource_type(
    engine: AsyncEngine, session_factory, facility_id, user_id
):
    patient_id = uuid.uuid4()
    match = await _insert_audit_row(
        engine, facility_id, user_id=user_id, patient_id=patient_id, resource_type="patients"
    )
    await _insert_audit_row(engine, facility_id, resource_type="orders")  # different user/resource_type

    async with session_factory() as db:
        items, total = await service.list_audit_logs(
            db, facility_id=facility_id, user_id=user_id,
            patient_id=patient_id, resource_type="patients",
        )

    assert total == 1
    assert items[0].id == match.id


async def test_list_filters_by_date_range(engine: AsyncEngine, session_factory, facility_id):
    now = datetime.now(timezone.utc)
    old_row = await _insert_audit_row(
        engine, facility_id, created_at=now - timedelta(days=10)
    )
    recent_row = await _insert_audit_row(
        engine, facility_id, created_at=now - timedelta(hours=1)
    )

    async with session_factory() as db:
        items, total = await service.list_audit_logs(
            db, facility_id=facility_id, date_from=now - timedelta(days=1), date_to=now,
        )

    ids = {i.id for i in items}
    assert total == 1
    assert recent_row.id in ids
    assert old_row.id not in ids


async def test_list_is_paginated_and_ordered_most_recent_first(
    engine: AsyncEngine, session_factory, facility_id
):
    rows = []
    for _ in range(3):
        rows.append(await _insert_audit_row(engine, facility_id))

    async with session_factory() as db:
        items, total = await service.list_audit_logs(
            db, facility_id=facility_id, page=1, page_size=2,
        )

    assert total == 3
    assert len(items) == 2
    assert items[0].created_at >= items[1].created_at, "expected most-recent-first ordering"


async def test_page_size_is_clamped_to_max(engine: AsyncEngine, session_factory, facility_id):
    async with session_factory() as db:
        items, _total = await service.list_audit_logs(
            db, facility_id=facility_id, page_size=10_000,
        )
    # Nothing to assert on `items` (0 rows seeded) — this proves the call
    # doesn't blow up / silently accept an unbounded page_size, exercising
    # _clamp_page_size directly instead.
    assert service._clamp_page_size(10_000) == service.MAX_PAGE_SIZE
    assert service._clamp_page_size(0) == 1


async def test_count_audit_logs_matches_list_total(
    engine: AsyncEngine, session_factory, facility_id
):
    for _ in range(4):
        await _insert_audit_row(engine, facility_id)

    async with session_factory() as db:
        count = await service.count_audit_logs(db, facility_id=facility_id)

    assert count == 4


async def test_csv_export_header_and_rows_match_filters(
    engine: AsyncEngine, bind_export_to_test_engine, facility_id, second_facility_id, user_id
):
    patient_id = uuid.uuid4()
    match = await _insert_audit_row(
        engine, facility_id, user_id=user_id, patient_id=patient_id,
        resource_type="patients", action="view",
    )
    await _insert_audit_row(engine, facility_id, resource_type="orders")  # excluded by filter
    await _insert_audit_row(engine, second_facility_id)  # excluded by facility scope

    chunks = [
        chunk
        async for chunk in service.stream_audit_logs_csv(
            facility_id=facility_id, resource_type="patients",
        )
    ]
    csv_text = "".join(chunks)
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    assert rows[0] == list(service.CSV_COLUMNS)
    assert len(rows) == 2, f"expected header + 1 data row, got {len(rows)} rows: {rows}"
    assert rows[1][0] == str(match.id)
    assert rows[1][1] == str(user_id)
    assert rows[1][3] == "view"
    assert rows[1][6] == str(patient_id)


async def test_csv_export_empty_result_is_header_only(
    engine: AsyncEngine, bind_export_to_test_engine, facility_id
):
    chunks = [
        chunk
        async for chunk in service.stream_audit_logs_csv(facility_id=facility_id)
    ]
    csv_text = "".join(chunks)
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    assert rows == [list(service.CSV_COLUMNS)]
