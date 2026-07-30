"""tests/test_queue_service.py

Runs against an isolated in-memory SQLite DB (see conftest.py) -- no
Postgres, Redis, or patients/visits modules required.

Run with: pytest tests/test_queue_service.py -v
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.notifications.models import NotificationHistory
from app.queue import service


pytestmark = pytest.mark.asyncio


async def test_create_queue_rejects_duplicate(db, seed):
    dept, room, doctor = seed
    from datetime import date
    await service.create_queue(db, dept.id, doctor.id, room.id, "label", date.today())
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, "label", date.today())
    assert exc.value.status_code == 409


async def test_create_token_sequence_and_display(db, queue):
    t1 = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    t2 = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    assert t1.sequence == 1
    assert t2.sequence == 2
    assert t1.token_display.endswith("-001")
    assert t2.token_display.endswith("-002")


async def test_create_token_requires_visit_id(db, queue):
    with pytest.raises(HTTPException) as exc:
        await service.create_token(db, queue.id, None, "normal")
    assert exc.value.status_code == 422


async def test_create_token_rejects_closed_queue(db, queue):
    queue.is_open = False
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    assert exc.value.status_code == 409


async def test_call_next_respects_priority_over_age(db, queue):
    normal_tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    emergency_tok = await service.create_token(db, queue.id, uuid.uuid4(), "emergency")

    called = await service.call_next_token(db, queue.id)
    assert called.id == emergency_tok.id  # emergency wins despite being younger


async def test_call_next_fifo_within_same_tier(db, queue):
    first = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    await asyncio.sleep(0.01)
    second = await service.create_token(db, queue.id, uuid.uuid4(), "normal")

    called = await service.call_next_token(db, queue.id)
    assert called.id == first.id


async def test_call_next_empty_queue_404(db, queue):
    with pytest.raises(HTTPException) as exc:
        await service.call_next_token(db, queue.id)
    assert exc.value.status_code == 404


async def test_call_next_publishes_and_records_notification(db, queue, monkeypatch):
    published = []

    async def fake_publish(channel, event_type, payload):
        published.append((channel, event_type, payload))

    monkeypatch.setattr(service, "publish_event", fake_publish)

    await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    called = await service.call_next_token(db, queue.id)

    assert len(published) == 1
    _, event_type, payload = published[0]
    assert event_type == "token_called"
    assert payload["token_display"] == called.token_display
    assert set(payload.keys()) == {
        "department_id", "queue_id", "doctor_name", "room_number",
        "token_display", "now_serving",
    }  # no patient name/UHID/mobile ever

    rows = (await db.execute(select(NotificationHistory))).scalars().all()
    assert len(rows) == 1


async def test_complete_by_visit_id_auto_advances(db, queue):
    visit_a = uuid.uuid4()
    tok_a = await service.create_token(db, queue.id, visit_a, "normal")
    tok_b = await service.create_token(db, queue.id, uuid.uuid4(), "normal")

    called = await service.call_next_token(db, queue.id)
    assert called.id == tok_a.id

    completed, next_called = await service.complete_by_visit_id(db, visit_a)
    assert completed.status == "completed"
    assert next_called is not None and next_called.id == tok_b.id


async def test_complete_by_visit_id_no_match_404(db, queue):
    with pytest.raises(HTTPException) as exc:
        await service.complete_by_visit_id(db, uuid.uuid4())
    assert exc.value.status_code == 404


async def test_undocumented_consult_leaves_token_stuck_not_blocking(db, queue):
    """'Doctor wrote nothing' scenario -- token sits as 'called', doesn't
    get auto-advanced past, doesn't crash or vanish."""
    visit_a = uuid.uuid4()
    tok_a = await service.create_token(db, queue.id, visit_a, "normal")
    tok_b = await service.create_token(db, queue.id, uuid.uuid4(), "normal")

    await service.call_next_token(db, queue.id)  # calls tok_a
    # No complete_by_visit_id call -- doctor documented nothing.

    result = await service.list_queue_tokens(db, queue.id)
    assert result["waiting_count"] == 1  # tok_b still waiting
    assert result["now_serving"] == tok_a.token_display  # still shown stuck


async def test_admin_call_next_blocked_loudly_by_stuck_token(db, queue):
    tok_a = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    await service.create_token(db, queue.id, uuid.uuid4(), "normal")

    await service.call_next_token(db, queue.id)  # calls tok_a, leaves it uncompleted

    with pytest.raises(HTTPException) as exc:
        await service.call_next_token(db, queue.id)
    assert exc.value.status_code == 409
    assert tok_a.token_display in str(exc.value.detail)


async def test_elevate_priority_changes_call_order(db, queue):
    older = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    newer = await service.create_token(db, queue.id, uuid.uuid4(), "normal")

    await service.elevate_priority(db, newer.id, "emergency")
    called = await service.call_next_token(db, queue.id)
    assert called.id == newer.id


async def test_elevate_priority_rejects_invalid_value(db, queue):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(db, tok.id, "not_a_real_priority")
    assert exc.value.status_code == 422


async def test_elevate_priority_rejects_non_callable_token(db, queue):
    tok = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    await service.call_next_token(db, queue.id)
    await service.admin_force_complete(db, tok.id)
    with pytest.raises(HTTPException) as exc:
        await service.elevate_priority(db, tok.id, "emergency")
    assert exc.value.status_code == 409


async def test_admin_force_complete_advances_queue(db, queue):
    tok_a = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    tok_b = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    await service.call_next_token(db, queue.id)  # calls tok_a

    completed, next_called = await service.admin_force_complete(db, tok_a.id)
    assert completed.status == "completed"
    assert next_called is not None and next_called.id == tok_b.id


async def test_list_queue_tokens_sorting_and_counts(db, queue):
    t_normal = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    t_emergency = await service.create_token(db, queue.id, uuid.uuid4(), "emergency")
    t_cancelled = await service.create_token(db, queue.id, uuid.uuid4(), "normal")
    t_cancelled.status = "cancelled"
    await db.flush()

    result = await service.list_queue_tokens(db, queue.id)
    ids = [i["id"] for i in result["items"]]

    assert t_cancelled.id not in ids
    assert ids[0] == t_emergency.id
    assert result["waiting_count"] == 2
    assert result["items"][0]["doctor_name"] is not None