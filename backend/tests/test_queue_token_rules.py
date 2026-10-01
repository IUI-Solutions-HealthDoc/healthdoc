"""Token issue, queue opening, visits-awaiting-token and priority retries.

Each rule here was a way for the reception queue to disagree with the visit
it represents: a second live token for one visit, a token for a visit that had
already ended, a token in yesterday's clinic or another department's, a queue
opened for a doctor nobody rostered, and a retried priority change reported
as a failure.
"""
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select

from app.audit.deps import get_current_actor_dependency
from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.departments.models import Department
from app.queue import router as queue_router
from app.queue import service
from app.queue.models import Queue, QueueTokenPriorityChange
from app.users.models import User
from tests.business_day import FACILITY_TZ, business_today

pytestmark = pytest.mark.asyncio


async def _issue(db, queue, visit):
    return await service.create_token(db, queue.id, visit.id, "normal", queue.facility_id)


def _code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.detail["code"]


# ---------------- token issue ----------------

async def test_a_visit_cannot_hold_two_live_tokens(db, seed, queue, opd_visit, roster_on_duty):
    dept, _room, _doctor = seed
    second_doctor = User(
        id=uuid.uuid4(), keycloak_sub=f"doc2-{uuid.uuid4()}", username=f"doc2{uuid.uuid4().hex[:6]}",
        full_name="Dr. Second", facility_id=dept.facility_id,
    )
    db.add(second_doctor)
    await db.flush()
    await roster_on_duty(dept.id, second_doctor.id)
    other_queue = await service.create_queue(
        db, dept.id, second_doctor.id, None, None, business_today(), dept.facility_id
    )
    visit = await opd_visit()
    await _issue(db, queue, visit)

    for target in (queue, other_queue):
        with pytest.raises(HTTPException) as exc:
            await _issue(db, target, visit)
        assert exc.value.status_code == 409
        assert _code(exc) == "live_token_exists"


async def test_a_new_token_is_allowed_once_the_old_one_has_ended(db, queue, opd_visit):
    visit = await opd_visit()
    first = await _issue(db, queue, visit)
    first.status = "cancelled"
    await db.flush()

    second = await _issue(db, queue, visit)
    assert second.status == "waiting"


@pytest.mark.parametrize("status", ["lwbs", "cancelled", "completed", "closed"])
async def test_an_ended_visit_takes_no_token(db, queue, opd_visit, status):
    visit = await opd_visit()
    visit.status = status
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await _issue(db, queue, visit)
    assert exc.value.status_code == 409
    assert _code(exc) == "visit_not_open"


async def test_yesterdays_queue_takes_no_new_token(db, seed, opd_visit):
    dept, room, doctor = seed
    stale_queue = Queue(
        id=uuid.uuid4(), facility_id=dept.facility_id, department_id=dept.id,
        doctor_user_id=doctor.id, room_id=room.id, service_date=business_today() - timedelta(days=1),
        is_open=True,
    )
    db.add(stale_queue)
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await _issue(db, stale_queue, await opd_visit())
    assert exc.value.status_code == 409
    assert _code(exc) == "queue_not_today"


async def test_a_visit_for_another_department_is_refused(db, seed, queue, opd_visit):
    dept, _room, _doctor = seed
    ortho = Department(id=uuid.uuid4(), code="ORT", name="Ortho", facility_id=dept.facility_id)
    db.add(ortho)
    await db.flush()
    visit = await opd_visit()
    visit.department_id = ortho.id
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await _issue(db, queue, visit)
    assert exc.value.status_code == 422
    assert _code(exc) == "department_mismatch"

    # A visit registered without a department may join any of today's queues.
    visit.department_id = None
    await db.flush()
    assert (await _issue(db, queue, visit)).status == "waiting"


# ---------------- queue opening ----------------

async def test_a_queue_opens_only_for_today(db, seed, roster_on_duty):
    dept, room, doctor = seed
    tomorrow = business_today() + timedelta(days=1)
    await roster_on_duty(dept.id, doctor.id, roster_date=tomorrow)

    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, None, tomorrow, dept.facility_id)
    assert exc.value.status_code == 422
    assert _code(exc) == "queue_date_not_today"


async def test_a_queue_needs_an_available_roster_entry_in_that_department(db, seed, roster_on_duty):
    dept, room, doctor = seed
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, None, business_today(), dept.facility_id)
    assert _code(exc) == "doctor_not_rostered"

    other = Department(id=uuid.uuid4(), code="OTH", name="Other", facility_id=dept.facility_id)
    db.add(other)
    await db.flush()
    await roster_on_duty(other.id, doctor.id)
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, None, business_today(), dept.facility_id)
    assert _code(exc) == "doctor_not_rostered", "a roster in another department does not count"

    entry = await roster_on_duty(dept.id, doctor.id, shift="evening")
    entry.is_available = False
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, None, business_today(), dept.facility_id)
    assert _code(exc) == "doctor_not_rostered", "an unavailable roster entry does not count"


async def test_opening_the_same_clinic_twice_is_a_conflict(db, seed, queue):
    dept, room, doctor = seed
    with pytest.raises(HTTPException) as exc:
        await service.create_queue(db, dept.id, doctor.id, room.id, None, business_today(), dept.facility_id)
    assert exc.value.status_code == 409
    assert _code(exc) == "queue_exists"


# ---------------- visits awaiting a token ----------------

async def test_visits_awaiting_a_token_are_todays_registered_visits_only(db, queue, opd_visit):
    # Inside the facility's business day, in its own timezone. SQLite keeps a
    # timestamp's wall-clock text without the offset, so a UTC stamp compares
    # against the IST day bounds as the wrong day between 18:30 and 24:00 UTC.
    in_today = datetime.combine(business_today(), time(1), tzinfo=ZoneInfo(FACILITY_TZ))
    waiting = await opd_visit()
    waiting.visit_date = in_today
    old = await opd_visit()
    old.visit_date = in_today - timedelta(days=2)
    tokened = await opd_visit()
    tokened.visit_date = in_today
    ended = await opd_visit()
    ended.visit_date = in_today
    ended.status = "lwbs"
    await db.flush()
    await _issue(db, queue, tokened)

    rows = await service.list_visits_without_tokens(db, queue.facility_id)
    assert [row["visit_id"] for row in rows] == [waiting.id]


# ---------------- priority change retries ----------------

def _client(db, actor, roles) -> httpx.AsyncClient:
    async def override_db():
        yield db

    app = FastAPI()
    app.include_router(queue_router.router)
    app.dependency_overrides[get_db] = override_db
    # The actor context reads users.id back through SQLite as a string, which
    # the audit row's UUID column cannot bind; attribution is not under test.
    app.dependency_overrides[get_current_actor_dependency] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=actor.keycloak_sub, username=actor.username, roles=roles
    )
    app.dependency_overrides[get_current_db_user] = lambda: DbUser(
        id=actor.id, keycloak_sub=actor.keycloak_sub, username=actor.username,
        facility_id=actor.facility_id, roles=roles,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_reconciliation_requires_an_idempotency_key(db, seed):
    _dept, _room, actor = seed
    body = {"visit_ids": [str(uuid.uuid4())], "reason": "Evening desk review of open visits"}
    async with _client(db, actor, ["receptionist"]) as client:
        resp = await client.post("/queue/reconcile-stale-visits", json=body)
    assert resp.status_code == 400


async def test_a_retried_priority_change_replays_instead_of_failing(db, seed, queue, opd_visit):
    dept, _room, _doctor = seed
    receptionist = User(
        id=uuid.uuid4(), keycloak_sub=f"recep-{uuid.uuid4()}", username=f"r{uuid.uuid4().hex[:6]}",
        full_name="Recep", facility_id=dept.facility_id,
    )
    db.add(receptionist)
    await db.flush()
    token = await _issue(db, queue, await opd_visit())
    body = {"priority": "senior_citizen", "reason": "age confirmed from the Aadhaar card"}
    path = f"/queue/tokens/{token.id}/priority"

    async with _client(db, receptionist, ["receptionist"]) as client:
        missing = await client.patch(path, json=body)
        assert missing.status_code == 400

        key = str(uuid.uuid4())
        first = await client.patch(path, json=body, headers={"Idempotency-Key": key})
        assert first.status_code == 200, first.text
        again = await client.patch(path, json=body, headers={"Idempotency-Key": key})
        assert again.status_code == 200
        assert again.json() == first.json()

    changes = (
        await db.execute(
            select(func.count()).select_from(QueueTokenPriorityChange)
            .where(QueueTokenPriorityChange.queue_token_id == token.id)
        )
    ).scalar_one()
    assert changes == 1
