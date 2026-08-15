"""Tests for task 9's notification history list (facility-scoped,
paginated). Tested directly against the service layer, no HTTP/JWT
needed.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.notifications import service
from app.notifications.models import NotificationHistory

pytestmark = pytest.mark.asyncio


async def _make_row(db, facility_id, department_id, event_type, created_at):
    db.add(NotificationHistory(
        id=uuid.uuid4(), event_type=event_type, payload={}, department_id=department_id,
        facility_id=facility_id, created_at=created_at,
    ))


async def test_list_scoped_to_facility(db):
    facility_a = uuid.uuid4()
    facility_b = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await _make_row(db, facility_a, None, "token_called", now)
    await _make_row(db, facility_b, None, "token_called", now)
    await db.flush()

    result = await service.list_notification_history(
        db, facility_a, department_id=None, event_type=None, page=1, page_size=20, sort="-created_at",
    )
    assert result["total"] == 1
    assert len(result["items"]) == 1


async def test_list_filters_by_department(db):
    facility_id = uuid.uuid4()
    dept_a = uuid.uuid4()
    dept_b = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await _make_row(db, facility_id, dept_a, "token_called", now)
    await _make_row(db, facility_id, dept_b, "token_called", now)
    await db.flush()

    result = await service.list_notification_history(
        db, facility_id, department_id=dept_a, event_type=None, page=1, page_size=20, sort="-created_at",
    )
    assert result["total"] == 1
    assert result["items"][0].department_id == dept_a


async def test_list_filters_by_event_type(db):
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await _make_row(db, facility_id, None, "token_called", now)
    await _make_row(db, facility_id, None, "queue_paused", now)
    await db.flush()

    result = await service.list_notification_history(
        db, facility_id, department_id=None, event_type="queue_paused", page=1, page_size=20, sort="-created_at",
    )
    assert result["total"] == 1
    assert result["items"][0].event_type == "queue_paused"


async def test_list_orders_newest_first_by_default(db):
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await _make_row(db, facility_id, None, "old_event", now - timedelta(minutes=10))
    await _make_row(db, facility_id, None, "new_event", now)
    await db.flush()

    result = await service.list_notification_history(
        db, facility_id, department_id=None, event_type=None, page=1, page_size=20, sort="-created_at",
    )
    assert result["items"][0].event_type == "new_event"
    assert result["items"][1].event_type == "old_event"


async def test_list_orders_oldest_first_when_ascending(db):
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await _make_row(db, facility_id, None, "old_event", now - timedelta(minutes=10))
    await _make_row(db, facility_id, None, "new_event", now)
    await db.flush()

    result = await service.list_notification_history(
        db, facility_id, department_id=None, event_type=None, page=1, page_size=20, sort="created_at",
    )
    assert result["items"][0].event_type == "old_event"
    assert result["items"][1].event_type == "new_event"


async def test_list_rejects_unsortable_field(db):
    facility_id = uuid.uuid4()
    with pytest.raises(Exception) as exc_info:
        await service.list_notification_history(
            db, facility_id, department_id=None, event_type=None, page=1, page_size=20, sort="-payload",
        )
    assert "Cannot sort by" in str(exc_info.value)


async def test_list_rejects_page_size_over_100(db):
    facility_id = uuid.uuid4()
    with pytest.raises(Exception) as exc_info:
        await service.list_notification_history(
            db, facility_id, department_id=None, event_type=None, page=1, page_size=500, sort="-created_at",
        )
    assert "422" in str(exc_info.value) or "cannot exceed" in str(exc_info.value)


async def test_list_pagination(db):
    facility_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    for i in range(5):
        await _make_row(db, facility_id, None, f"event_{i}", now - timedelta(minutes=i))
    await db.flush()

    page_1 = await service.list_notification_history(
        db, facility_id, department_id=None, event_type=None, page=1, page_size=2, sort="-created_at",
    )
    page_2 = await service.list_notification_history(
        db, facility_id, department_id=None, event_type=None, page=2, page_size=2, sort="-created_at",
    )

    assert page_1["total"] == 5
    assert len(page_1["items"]) == 2
    assert len(page_2["items"]) == 2
    assert page_1["items"][0].id != page_2["items"][0].id
