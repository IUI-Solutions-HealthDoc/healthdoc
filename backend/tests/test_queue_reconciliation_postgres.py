"""Real PostgreSQL: stale-visit reconciliation and the two queue races.

Reconciliation compares visit dates in the facility's zone with
`timezone()`, which SQLite does not have, and the races are decided by row
locks and unique indexes that only a real server enforces.
"""
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.audit.models import AuditLog
from app.departments.models import Department
from app.opd.models import Visit
from app.patients.models import Patient
from app.queue import reconciliation, service
from app.queue.models import Queue, QueueToken, Roster
from app.users.models import Facility, User
from tests.pg_fixtures import db, engine  # noqa: F401

pytestmark = pytest.mark.asyncio

REASON = "Evening desk review of visits left open"


async def _world(session):
    facility = Facility(
        id=uuid.uuid4(), code="RC" + uuid.uuid4().hex[:6].upper(),
        name="Reconciliation test facility", state_code="DL", timezone="Asia/Kolkata",
    )
    session.add(facility)
    await session.flush()
    dept = Department(id=uuid.uuid4(), code="RCD", name="Reconcile Dept", facility_id=facility.id)
    actor = User(
        id=uuid.uuid4(), keycloak_sub=f"rc-{uuid.uuid4()}", username=f"rc{uuid.uuid4().hex[:10]}",
        full_name="Desk", facility_id=facility.id,
    )
    session.add_all([dept, actor])
    await session.flush()
    return facility, dept, actor


async def _visit(session, facility, dept, actor, *, status="registered", days_ago=2):
    patient = Patient(
        id=uuid.uuid4(), full_name="Stale Visit Patient", sex="other",
        identity_path="demographics_only", facility_id=facility.id, created_by=actor.id,
        age_years=40, uhid=f"IN-DL-RCON-2026-{uuid.uuid4().hex[:12]}",
    )
    session.add(patient)
    await session.flush()
    visit = Visit(
        id=uuid.uuid4(), visit_number=f"VST-RC-{uuid.uuid4().hex[:12]}", patient_id=patient.id,
        facility_id=facility.id, department_id=dept.id, visit_type="opd", status=status,
        visit_date=datetime.now(UTC) - timedelta(days=days_ago), created_by=actor.id,
    )
    session.add(visit)
    await session.flush()
    return visit


async def _live_token(session, facility, dept, actor, visit, days_ago=2):
    queue = Queue(
        id=uuid.uuid4(), facility_id=facility.id, department_id=dept.id, doctor_user_id=actor.id,
        service_date=(datetime.now(UTC) - timedelta(days=days_ago)).date(), is_open=True,
    )
    session.add(queue)
    await session.flush()
    token = QueueToken(
        id=uuid.uuid4(), facility_id=facility.id, queue_id=queue.id, visit_id=visit.id,
        sequence=1, token_display="RCD-001", initial_priority="normal", status="called",
        priority="normal", priority_rank=6,
    )
    session.add(token)
    await session.flush()
    queue.now_serving_token_id = token.id
    await session.flush()
    return queue, token


async def test_report_lists_each_stale_visit_once_whatever_the_facility_count(db):
    facility, dept, actor = await _world(db)
    await _world(db)  # a second facility used to repeat every row
    stale = await _visit(db, facility, dept, actor)
    await _visit(db, facility, dept, actor, days_ago=0)

    report = await reconciliation.get_stale_visits_candidates(db, facility.id)

    assert [c.visit_id for c in report.candidates] == [stale.id]
    assert report.total_stale_count == 1


async def test_reconciling_selected_visits_uses_the_state_machine_and_audits_the_reason(db):
    facility, dept, actor = await _world(db)
    waited = await _visit(db, facility, dept, actor)
    queue, token = await _live_token(db, facility, dept, actor, waited)
    in_consult = await _visit(db, facility, dept, actor, status="in_consultation")
    today = await _visit(db, facility, dept, actor, days_ago=0)

    result = await reconciliation.reconcile_stale_visits(
        db, facility.id, actor.id, reason=REASON, visit_ids=[waited.id, today.id],
    )

    assert result.reconciled_visits == [waited.id]
    assert [d["visit_id"] for d in result.skipped_details] == [str(today.id)]
    await db.refresh(waited)
    await db.refresh(token)
    await db.refresh(queue)
    await db.refresh(in_consult)
    assert waited.status == "lwbs"
    assert token.status == "no_show" and token.completed_at is not None
    assert queue.now_serving_token_id is None
    assert in_consult.status == "in_consultation", "only the listed visits are touched"

    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.resource_type == "visits", AuditLog.resource_id == waited.id)
        )
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].old_value == {"status": "registered"}
    assert audit[0].new_value["status"] == "lwbs"
    assert audit[0].new_value["tokens_marked_no_show"] == [str(token.id)]
    assert REASON in audit[0].reason
    assert audit[0].user_id == actor.id


async def test_reconciling_everything_closes_consultations_and_skips_other_facilities(db):
    facility, dept, actor = await _world(db)
    other_facility, other_dept, other_actor = await _world(db)
    in_consult = await _visit(db, facility, dept, actor, status="in_consultation")
    elsewhere = await _visit(db, other_facility, other_dept, other_actor)

    result = await reconciliation.reconcile_stale_visits(
        db, facility.id, actor.id, reason=REASON, visit_ids=None,
    )

    assert result.reconciled_visits == [in_consult.id]
    await db.refresh(in_consult)
    await db.refresh(elsewhere)
    assert in_consult.status == "closed"
    assert elsewhere.status == "registered"


# ---------------- races: committed data, two sessions ----------------

def _url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs real PostgreSQL — run `make test-pg` from the repo root")
    return url


async def test_two_desks_issuing_for_one_visit_get_one_token_and_one_conflict():
    eng = create_async_engine(_url())
    assert "test" in (eng.url.database or "").lower(), "Use a dedicated test database"
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session.begin() as session:
            facility, dept, actor = await _world(session)
            visit = await _visit(session, facility, dept, actor, days_ago=0)
            # The service's own clock, which the suite's conftest may pin.
            today = await service.get_business_date(session, facility.id)
            queues = []
            for n in range(2):
                doctor = User(
                    id=uuid.uuid4(), keycloak_sub=f"rcd-{uuid.uuid4()}",
                    username=f"rcd{uuid.uuid4().hex[:10]}", full_name=f"Dr {n}", facility_id=facility.id,
                )
                session.add(doctor)
                await session.flush()
                queue = Queue(
                    id=uuid.uuid4(), facility_id=facility.id, department_id=dept.id,
                    doctor_user_id=doctor.id, service_date=today, is_open=True,
                )
                session.add(queue)
                queues.append(queue)
            await session.flush()

        async def second_desk():
            async with Session.begin() as session:
                await service.create_token(session, queues[1].id, visit.id, "normal", facility.id)

        # Desk A has written its token but not committed when desk B starts,
        # so B cannot see it and must be stopped by the lock or the index.
        async with Session.begin() as session:
            await service.create_token(session, queues[0].id, visit.id, "normal", facility.id)
            desk_b = asyncio.create_task(second_desk())
            await asyncio.sleep(0.5)
            assert not desk_b.done(), "desk B must wait for desk A, not run past it"

        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(desk_b, timeout=15)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "live_token_exists"
        async with Session() as session:
            live = (
                await session.execute(select(QueueToken).where(QueueToken.visit_id == visit.id))
            ).scalars().all()
            assert len(live) == 1
    finally:
        await eng.dispose()


async def test_two_desks_opening_one_clinic_get_one_queue_and_one_conflict():
    eng = create_async_engine(_url())
    assert "test" in (eng.url.database or "").lower(), "Use a dedicated test database"
    Session = async_sessionmaker(eng, expire_on_commit=False)
    try:
        async with Session.begin() as session:
            facility, dept, doctor = await _world(session)
            today = await service.get_business_date(session, facility.id)
            session.add(Roster(
                id=uuid.uuid4(), staff_user_id=doctor.id, department_id=dept.id,
                shift="morning", roster_date=today, is_available=True,
            ))

        async def second_desk():
            async with Session.begin() as session:
                await service.create_queue(session, dept.id, doctor.id, None, None, today, facility.id)

        # Both desks pass the "already open?" read; the unique index decides.
        async with Session.begin() as session:
            await service.create_queue(session, dept.id, doctor.id, None, None, today, facility.id)
            desk_b = asyncio.create_task(second_desk())
            await asyncio.sleep(0.5)
            assert not desk_b.done(), "desk B must block on the unique index"

        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(desk_b, timeout=15)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "queue_exists"
        async with Session() as session:
            opened = (
                await session.execute(select(Queue).where(Queue.doctor_user_id == doctor.id))
            ).scalars().all()
            assert len(opened) == 1
    finally:
        await eng.dispose()
