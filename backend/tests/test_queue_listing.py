"""GET /queue/queues — the endpoint that lets a queue be chosen.

POST /queue/tokens takes a queue_id and nothing returned one. /worklist is a
doctor's own list and doctor/admin-only, and creating a queue is not the same as
finding today's. So a token could only be issued by someone who already knew a
UUID, which meant it could not be issued from a screen at all.

What is pinned here is what makes the list usable rather than merely present:
facility scoping, the service_date window, the waiting count, and closed queues
staying out by default.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.common.enums import QueuePriority
from app.departments.models import Department
from app.opd.models import Visit
from app.patients.models import Patient
from app.queue import service
from app.queue.models import Roster
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio

TODAY = date.today()


async def _token(db, queue, visit_id=None):
    return await service.create_token(
        db,
        queue_id=queue.id,
        visit_id=visit_id or uuid.uuid4(),
        priority=QueuePriority.NORMAL.value,
        caller_facility_id=queue.facility_id,
    )


async def test_list_returns_todays_queue_with_who_and_where(db, seed, queue):
    """A queue id alone is not a choice anyone can make."""
    dept, room, doctor = seed

    rows = await service.list_queues(db, dept.facility_id, TODAY)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == queue.id
    assert row["doctor_name"] == doctor.full_name, "the receptionist picks a doctor, not a UUID"
    assert row["room_number"] == room.room_number
    assert row["waiting_count"] == 0
    assert row["now_serving"] is None


async def test_waiting_count_is_the_number_a_walk_in_is_routed_by(db, seed, queue):
    """Included on the row deliberately: computing it client-side would mean a
    request per doctor on the first screen of every morning."""
    await _token(db, queue)
    await _token(db, queue)

    (row,) = await service.list_queues(db, queue.facility_id, TODAY)
    assert row["waiting_count"] == 2


async def test_reception_queue_identifies_the_patient_attached_to_each_token(db, seed, queue):
    """A token number alone is not enough at a busy counter; reception must
    confirm the chart before changing its priority or answering a query."""
    dept, _room, doctor = seed
    patient = Patient(
        id=uuid.uuid4(),
        uhid="IN-TS-TST01-2026-000001-0",
        full_name="Asha Menon",
        sex="female",
        age_years=36,
        identity_path="demographics_only",
        facility_id=dept.facility_id,
        created_by=doctor.id,
    )
    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        facility_id=dept.facility_id,
        visit_type="opd",
        visit_date=datetime.now(UTC),
        created_by=doctor.id,
    )
    db.add_all([patient, visit])
    await db.flush()
    await _token(db, queue, visit.id)

    result = await service.list_queue_tokens(db, queue.id, dept.facility_id)

    assert result["items"][0]["patient_name"] == "Asha Menon"
    assert result["items"][0]["patient_identifier"] == patient.uhid


async def test_another_facilitys_queues_are_not_listed(db, seed, queue):
    """Facility scoping, same rule as every other list in this codebase."""
    other_facility = Facility(
        id=uuid.uuid4(), code=f"OT{uuid.uuid4().hex[:3].upper()}",
        name="Other Facility", state_code="TS",
    )
    db.add(other_facility)
    await db.flush()

    other_dept = Department(
        id=uuid.uuid4(), code="OTD", name="Other Dept", facility_id=other_facility.id,
    )
    other_doctor = User(
        id=uuid.uuid4(), keycloak_sub=f"other-{uuid.uuid4()}",
        username=f"otherdoc{uuid.uuid4().hex[:6]}", full_name="Dr. Other",
        facility_id=other_facility.id,
    )
    db.add_all([other_dept, other_doctor])
    await db.flush()

    await service.create_queue(
        db, department_id=other_dept.id, doctor_user_id=other_doctor.id,
        room_id=None, display_label="Other", service_date=TODAY,
        caller_facility_id=other_facility.id,
    )

    ours = await service.list_queues(db, queue.facility_id, TODAY)
    theirs = await service.list_queues(db, other_facility.id, TODAY)

    assert [r["id"] for r in ours] == [queue.id]
    assert queue.id not in [r["id"] for r in theirs]


async def test_yesterdays_queues_are_not_offered(db, seed, queue):
    """Queues are unique per (department, doctor, service_date), so without the
    date filter a reception screen would offer yesterday's rows beside today's
    and a walk-in could be booked into a clinic that has already ended."""
    rows = await service.list_queues(db, queue.facility_id, TODAY - timedelta(days=1))
    assert rows == []


async def test_closed_queues_are_hidden_by_default_but_reachable(db, seed, queue):
    """A paused or closed clinic is not somewhere to send a patient. It is still
    worth being able to see one, so open_only is a parameter rather than a
    hardcoded filter."""
    await service.pause_queue(
        db, queue.id, queue.facility_id,
        caller_roles=["admin"], caller_department_id=queue.department_id,
    )

    assert await service.list_queues(db, queue.facility_id, TODAY) == []

    all_rows = await service.list_queues(db, queue.facility_id, TODAY, open_only=False)
    assert [r["id"] for r in all_rows] == [queue.id]
    assert all_rows[0]["is_open"] is False


async def test_opening_options_are_named_facility_scoped_available_roster_rows(db, seed):
    dept, room, doctor = seed
    roster = Roster(
        id=uuid.uuid4(),
        staff_user_id=doctor.id,
        department_id=dept.id,
        room_id=room.id,
        shift="morning",
        roster_date=TODAY,
        is_available=True,
    )
    db.add(roster)
    await db.flush()

    options = await service.list_queue_opening_options(db, dept.facility_id, TODAY)

    assert options == [{
        "roster_id": roster.id,
        "staff_user_id": doctor.id,
        "staff_name": doctor.full_name,
        "department_id": dept.id,
        "department_name": dept.name,
        "room_id": room.id,
        "room_number": room.room_number,
        "shift": "morning",
    }]

    await service.create_queue(
        db, dept.id, doctor.id, room.id, None, TODAY, dept.facility_id
    )
    assert await service.list_queue_opening_options(db, dept.facility_id, TODAY) == []


async def test_shortest_queue_first(db, seed, queue):
    """The order a receptionist reads it in."""
    dept, _room, _doctor = seed

    busy_doctor = User(
        id=uuid.uuid4(), keycloak_sub=f"busy-{uuid.uuid4()}",
        username=f"busydoc{uuid.uuid4().hex[:6]}", full_name="Dr. Busy",
        facility_id=dept.facility_id,
    )
    db.add(busy_doctor)
    await db.flush()

    busy_queue = await service.create_queue(
        db, department_id=dept.id, doctor_user_id=busy_doctor.id,
        room_id=None, display_label="Busy", service_date=TODAY,
        caller_facility_id=dept.facility_id,
    )
    await _token(db, busy_queue)

    rows = await service.list_queues(db, dept.facility_id, TODAY)
    assert [r["waiting_count"] for r in rows] == [0, 1]
