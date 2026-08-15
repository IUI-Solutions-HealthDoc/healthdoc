"""Tests for notifications/router.py's _catch_up_department_events() --
the reconnect/Last-Event-ID replay logic. Tested directly, not through
HTTP, since this endpoint is a StreamingResponse and would hit the same
EnvelopeMiddleware/BaseHTTPMiddleware deadlock as queue's SSE endpoint
if tested via an in-process ASGI client (see test_queue_sse.py).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.notifications.models import NotificationHistory
from app.notifications.router import _catch_up_department_events

pytestmark = pytest.mark.asyncio


async def test_catch_up_returns_nothing_when_no_history(db):
    department_id = uuid.uuid4()
    result = await _catch_up_department_events(db, department_id, None)
    assert result == []


async def test_catch_up_returns_all_history_when_no_last_event_id(db):
    department_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    row1 = NotificationHistory(
        id=uuid.uuid4(), event_type="low_stock_alert", payload={"a": 1},
        department_id=department_id, facility_id=facility_id, created_at=now - timedelta(minutes=10),
    )
    row2 = NotificationHistory(
        id=uuid.uuid4(), event_type="critical_value_alert", payload={"b": 2},
        department_id=department_id, facility_id=facility_id, created_at=now - timedelta(minutes=5),
    )
    db.add_all([row1, row2])
    await db.flush()

    result = await _catch_up_department_events(db, department_id, None)
    assert len(result) == 2
    assert result[0].id == row1.id
    assert result[1].id == row2.id


async def test_catch_up_only_returns_events_after_last_event_id(db):
    department_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old_row = NotificationHistory(
        id=uuid.uuid4(), event_type="lab_report_ready", payload={},
        department_id=department_id, facility_id=facility_id, created_at=now - timedelta(minutes=20),
    )
    new_row = NotificationHistory(
        id=uuid.uuid4(), event_type="lab_report_ready", payload={},
        department_id=department_id, facility_id=facility_id, created_at=now - timedelta(minutes=1),
    )
    db.add_all([old_row, new_row])
    await db.flush()

    last_event_id = (now - timedelta(minutes=10)).isoformat()
    result = await _catch_up_department_events(db, department_id, last_event_id)
    assert len(result) == 1
    assert result[0].id == new_row.id


async def test_catch_up_ignores_malformed_last_event_id(db):
    department_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    row = NotificationHistory(
        id=uuid.uuid4(), event_type="low_stock_alert", payload={},
        department_id=department_id, facility_id=facility_id, created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()

    result = await _catch_up_department_events(db, department_id, "not-a-valid-timestamp")
    assert len(result) == 1


async def test_catch_up_scopes_by_department(db):
    dept_a = uuid.uuid4()
    dept_b = uuid.uuid4()
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    row_a = NotificationHistory(
        id=uuid.uuid4(), event_type="low_stock_alert", payload={}, department_id=dept_a,
        facility_id=facility_id, created_at=now,
    )
    row_b = NotificationHistory(
        id=uuid.uuid4(), event_type="low_stock_alert", payload={}, department_id=dept_b,
        facility_id=facility_id, created_at=now,
    )
    db.add_all([row_a, row_b])
    await db.flush()

    result = await _catch_up_department_events(db, dept_a, None)
    assert len(result) == 1
    assert result[0].id == row_a.id
