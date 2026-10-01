"""Appointment scope, state rules, time validation, check-in tokens and idempotency."""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import func, select

from app.appointments import router as appointments_router
from app.appointments import service
from app.appointments.models import Appointment, AppointmentService
from app.appointments.schemas import (
    AppointmentCheckInRequest,
    AppointmentCreate,
    AppointmentUpdate,
)
from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.common.db import get_db
from app.departments.models import Department
from app.opd.models import Visit
from app.patients.models import Patient
from app.queue import service as queue_service
from app.queue.models import Roster
from app.users.models import Facility, User

TZ = "Asia/Kolkata"


def _today() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


def _patient(facility_id, created_by) -> Patient:
    suffix = uuid.uuid4().hex[:10]
    return Patient(
        id=uuid.uuid4(), uhid=f"UH{suffix}", full_name="Appointment Patient", sex="unknown",
        age_years=30, identity_path="demographics_only", facility_id=facility_id, created_by=created_by,
    )


@pytest.fixture
async def world(db, seed):
    dept, room, doctor = seed
    patient = _patient(dept.facility_id, doctor.id)
    other_facility = Facility(id=uuid.uuid4(), code="OTH01", name="Other Facility", state_code="TS")
    db.add_all([patient, other_facility])
    await db.flush()
    other_dept = Department(id=uuid.uuid4(), code="OTH", name="Other Dept", facility_id=other_facility.id)
    other_doctor = User(
        id=uuid.uuid4(), keycloak_sub=f"other-{uuid.uuid4()}", username=f"oth{uuid.uuid4().hex[:6]}",
        full_name="Dr. Elsewhere", facility_id=other_facility.id,
    )
    other_patient = _patient(other_facility.id, doctor.id)
    db.add_all([other_dept, other_doctor, other_patient])
    await db.flush()
    return {
        "facility_id": dept.facility_id, "dept": dept, "room": room, "doctor": doctor, "patient": patient,
        "other_dept": other_dept, "other_doctor": other_doctor, "other_patient": other_patient,
    }


@pytest.fixture
def fake_visit(monkeypatch):
    """create_visit also raises the registration invoice, which needs a tariff
    this fixture does not seed; the check-in rules under test sit around it."""
    created: list[Visit] = []

    async def fake_create_visit(db, payload, facility_code, facility_timezone, created_by, facility_id):
        visit = Visit(
            id=uuid.uuid4(), visit_number=f"V-{uuid.uuid4().hex[:10]}", patient_id=payload.patient_id,
            facility_id=facility_id, department_id=payload.department_id, visit_type=payload.visit_type,
            visit_date=datetime.now(), created_by=created_by,
        )
        db.add(visit)
        await db.flush()
        created.append(visit)
        return visit

    monkeypatch.setattr(service, "create_visit", fake_create_visit)
    return created


def _booking(w, **overrides) -> AppointmentCreate:
    data = {
        "patient_id": w["patient"].id, "department_id": w["dept"].id, "doctor_user_id": w["doctor"].id,
        "appointment_date": _today(), "start_time": "10:00", "duration_minutes": 15,
    }
    data.update(overrides)
    return AppointmentCreate(**data)


async def _book(db, w, **overrides) -> Appointment:
    return await service.create_appointment(db, w["facility_id"], w["doctor"].id, _booking(w, **overrides))


async def _open_queue(db, w, *, is_open=True):
    # Queues are opened from the HOD roster, so the doctor is rostered first.
    db.add(Roster(
        id=uuid.uuid4(), staff_user_id=w["doctor"].id, department_id=w["dept"].id,
        room_id=w["room"].id, shift="morning", roster_date=_today(), is_available=True,
    ))
    await db.flush()
    queue = await queue_service.create_queue(
        db, department_id=w["dept"].id, doctor_user_id=w["doctor"].id, room_id=w["room"].id,
        display_label="Q", service_date=_today(), caller_facility_id=w["facility_id"],
    )
    queue.is_open = is_open
    await db.flush()
    return queue


async def _check_in(db, w, appt, **payload):
    return await service.check_in_appointment(
        db, w["facility_id"], w["doctor"].id, appt.id, AppointmentCheckInRequest(**payload),
        facility_code="TST01", facility_timezone=TZ,
    )


# ---------------- time validation ----------------

@pytest.mark.parametrize("value", ["25:00", "24:00", "12:60", "9:00", "99:99"])
def test_start_time_outside_the_day_is_rejected_by_the_schema(value):
    with pytest.raises(ValidationError):
        AppointmentCreate(patient_id=uuid.uuid4(), department_id=uuid.uuid4(),
                          appointment_date=date(2026, 10, 1), start_time=value)


def test_last_minute_of_the_day_is_accepted():
    AppointmentCreate(patient_id=uuid.uuid4(), department_id=uuid.uuid4(),
                      appointment_date=date(2026, 10, 1), start_time="23:59", duration_minutes=5)


def test_slot_crossing_midnight_is_refused():
    with pytest.raises(service.AppointmentValidationError):
        service.calc_end_time("23:50", 30)
    assert service.calc_end_time("23:30", 29) == "23:59"


def test_update_rejects_an_unknown_status():
    with pytest.raises(ValidationError):
        AppointmentUpdate(status="whatever")


# ---------------- facility scope ----------------

@pytest.mark.parametrize("field,target", [
    ("patient_id", "other_patient"),
    ("department_id", "other_dept"),
    ("doctor_user_id", "other_doctor"),
])
async def test_booking_refuses_another_facilitys_references(db, world, field, target):
    with pytest.raises(service.AppointmentNotFoundError):
        await _book(db, world, **{field: world[target].id})


async def test_booking_refuses_a_follow_up_visit_of_another_patient(db, world, opd_visit):
    foreign_visit = await opd_visit()
    with pytest.raises(service.AppointmentNotFoundError):
        await _book(db, world, follow_up_from_visit_id=foreign_visit.id)


async def test_catalogue_service_sets_name_and_duration(db, world):
    svc = AppointmentService(id=uuid.uuid4(), facility_id=world["facility_id"], name="Dressing",
                             duration_minutes=30, is_active=True)
    db.add(svc)
    await db.flush()
    appt = await _book(db, world, service_id=svc.id, service_name="Forged", duration_minutes=5)
    assert (appt.service_name, appt.duration_minutes, appt.end_time) == ("Dressing", 30, "10:30")


async def test_list_hides_rows_whose_patient_is_in_another_facility(db, world):
    own = await _book(db, world)
    foreign = Appointment(
        id=uuid.uuid4(), facility_id=world["facility_id"], patient_id=world["other_patient"].id,
        department_id=world["dept"].id, service_name="X", duration_minutes=15,
        appointment_date=_today(), start_time="11:00", end_time="11:15", status="booked",
        created_by=world["doctor"].id,
    )
    db.add(foreign)
    await db.flush()
    rows = await service.list_appointments(db, world["facility_id"])
    assert [row["id"] for row in rows] == [own.id]


# ---------------- scheduling rules ----------------

async def test_booking_in_the_past_is_refused(db, world):
    with pytest.raises(service.AppointmentValidationError):
        await _book(db, world, appointment_date=_today() - timedelta(days=1))


async def test_overlapping_booking_for_the_same_doctor_is_refused(db, world):
    await _book(db, world)
    with pytest.raises(service.AppointmentConflictError):
        await _book(db, world, start_time="10:10")


async def test_reschedule_checks_conflicts_but_not_against_itself(db, world):
    first = await _book(db, world)
    second = await _book(db, world, start_time="11:00")
    moved = await service.update_appointment(
        db, world["facility_id"], world["doctor"].id, first.id, AppointmentUpdate(start_time="10:05"),
    )
    assert (moved.start_time, moved.end_time) == ("10:05", "10:20")
    with pytest.raises(service.AppointmentConflictError):
        await service.update_appointment(
            db, world["facility_id"], world["doctor"].id, second.id, AppointmentUpdate(start_time="10:10"),
        )


async def test_changing_only_the_duration_recomputes_the_end(db, world):
    appt = await _book(db, world)
    updated = await service.update_appointment(
        db, world["facility_id"], world["doctor"].id, appt.id, AppointmentUpdate(duration_minutes=45),
    )
    assert updated.end_time == "10:45"


async def test_reschedule_to_the_past_is_refused(db, world):
    appt = await _book(db, world)
    with pytest.raises(service.AppointmentValidationError):
        await service.update_appointment(
            db, world["facility_id"], world["doctor"].id, appt.id,
            AppointmentUpdate(appointment_date=_today() - timedelta(days=1)),
        )


@pytest.mark.parametrize("start,target,allowed", [
    ("booked", "confirmed", True),
    ("booked", "no_show", True),
    ("confirmed", "no_show", True),
    ("checked_in", "completed", True),
    ("confirmed", "booked", False),
    ("cancelled", "booked", False),
    ("cancelled", "confirmed", False),
    ("checked_in", "cancelled", False),
    ("completed", "booked", False),
    ("booked", "checked_in", False),
])
async def test_status_transitions(db, world, start, target, allowed):
    appt = await _book(db, world)
    appt.status = start
    await db.flush()
    change = AppointmentUpdate(status=target)
    if allowed:
        updated = await service.update_appointment(db, world["facility_id"], world["doctor"].id, appt.id, change)
        assert updated.status == target
    else:
        with pytest.raises(service.AppointmentStateError):
            await service.update_appointment(db, world["facility_id"], world["doctor"].id, appt.id, change)


async def test_cancel_requires_a_reason(db, world):
    appt = await _book(db, world)
    with pytest.raises(service.AppointmentValidationError):
        await service.update_appointment(
            db, world["facility_id"], world["doctor"].id, appt.id, AppointmentUpdate(status="cancelled"),
        )
    cancelled = await service.update_appointment(
        db, world["facility_id"], world["doctor"].id, appt.id,
        AppointmentUpdate(status="cancelled", cancellation_reason="Patient called to cancel"),
    )
    assert cancelled.status == "cancelled"


async def test_a_cancelled_appointment_cannot_be_rescheduled(db, world):
    appt = await _book(db, world)
    appt.status = "cancelled"
    await db.flush()
    with pytest.raises(service.AppointmentStateError):
        await service.update_appointment(
            db, world["facility_id"], world["doctor"].id, appt.id, AppointmentUpdate(start_time="12:00"),
        )


# ---------------- check-in ----------------

async def test_check_in_uses_the_doctors_open_queue(db, world, fake_visit):
    await _open_queue(db, world)
    appt = await _book(db, world)
    result = await _check_in(db, world, appt)
    assert result.token_status == "issued"
    assert result.token_display
    assert result.token_not_issued_reason is None
    assert appt.token_id == result.token_id


async def test_check_in_without_an_open_queue_says_no_token(db, world, fake_visit):
    appt = await _book(db, world)
    result = await _check_in(db, world, appt)
    assert (result.token_status, result.token_id, result.token_display) == ("not_issued", None, None)
    assert result.token_not_issued_reason == "no_open_queue"
    assert result.visit_id == fake_visit[0].id
    assert appt.status == "checked_in"


async def test_refused_token_keeps_the_visit_and_reports_why(db, world, fake_visit):
    queue = await _open_queue(db, world, is_open=False)
    appt = await _book(db, world)
    result = await _check_in(db, world, appt, queue_id=queue.id)
    assert result.token_status == "not_issued"
    assert "closed" in result.token_not_issued_reason.lower()
    assert await db.get(Visit, result.visit_id) is not None


async def test_second_check_in_returns_the_first_visit(db, world, fake_visit):
    await _open_queue(db, world)
    appt = await _book(db, world)
    first = await _check_in(db, world, appt)
    again = await _check_in(db, world, appt)
    assert (again.visit_id, again.token_id) == (first.visit_id, first.token_id)
    assert len(fake_visit) == 1


@pytest.mark.parametrize("status", ["cancelled", "no_show", "completed"])
async def test_check_in_refuses_closed_appointments(db, world, fake_visit, status):
    appt = await _book(db, world)
    appt.status = status
    await db.flush()
    with pytest.raises(service.AppointmentStateError):
        await _check_in(db, world, appt)
    assert fake_visit == []


async def test_check_in_refuses_another_days_appointment(db, world, fake_visit):
    appt = await _book(db, world, appointment_date=_today() + timedelta(days=1))
    with pytest.raises(service.AppointmentStateError):
        await _check_in(db, world, appt)
    assert fake_visit == []


# ---------------- router: keys and receipts ----------------

def _caller(w) -> DbUser:
    doctor = w["doctor"]
    return DbUser(id=doctor.id, keycloak_sub=doctor.keycloak_sub, username=doctor.username,
                  facility_id=w["facility_id"], roles=["receptionist"])


def _client(db, caller: DbUser, key: str | None) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(appointments_router.router)

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=caller.roles)
    app.dependency_overrides[get_current_db_user] = lambda: caller
    headers = {"Idempotency-Key": key} if key else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers=headers)


def _body(w) -> dict:
    return {
        "patient_id": str(w["patient"].id), "department_id": str(w["dept"].id),
        "appointment_date": _today().isoformat(), "start_time": "10:00",
    }


@pytest.mark.parametrize("method,path,body", [
    ("post", "/appointments", "booking"),
    ("post", "/appointments/services", {"name": "Dressing"}),
    ("patch", "/appointments/{id}", {}),
    ("post", "/appointments/{id}/check-in", {}),
])
async def test_writes_without_an_idempotency_key_are_refused(db, world, method, path, body):
    payload = _body(world) if body == "booking" else body
    async with _client(db, _caller(world), None) as client:
        response = await client.request(method.upper(), path.format(id=uuid.uuid4()), json=payload)
    assert response.status_code == 400
    assert await db.scalar(select(func.count()).select_from(Appointment)) == 0


async def test_replayed_booking_returns_the_first_result_and_books_once(db, world):
    key = str(uuid.uuid4())
    async with _client(db, _caller(world), key) as client:
        first = await client.post("/appointments", json=_body(world))
        second = await client.post("/appointments", json=_body(world))
    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    count = await db.scalar(select(func.count()).select_from(Appointment))
    assert count == 1


async def test_router_maps_state_and_validation_errors(db, world):
    appt = await _book(db, world)
    async with _client(db, _caller(world), str(uuid.uuid4())) as client:
        invalid = await client.patch(f"/appointments/{appt.id}", json={"status": "booked"})
    async with _client(db, _caller(world), str(uuid.uuid4())) as client:
        no_reason = await client.patch(f"/appointments/{appt.id}", json={"status": "cancelled"})
    async with _client(db, _caller(world), str(uuid.uuid4())) as client:
        foreign = await client.patch(f"/appointments/{uuid.uuid4()}", json={"status": "confirmed"})
    assert invalid.status_code == 200  # booked -> booked is a no-op, not a transition
    assert no_reason.status_code == 422
    assert foreign.status_code == 404
