"""A patient asks for an appointment from the portal; reception books or declines it."""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.appointments import router as appointments_router
from app.common import patient_scope
from app.patients import portal_self_router as portal

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 10, 10)


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    async def today(_db, _facility_id):
        return TODAY
    monkeypatch.setattr(portal, "facility_today", today)
    monkeypatch.setattr(patient_scope, "facility_today", today)


async def _world(db):
    fid, dept, other_dept, patient = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    portal_user, desk_user, doctor, other_desk = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    other_facility = uuid.uuid4()
    run = db.execute
    for f in (fid, other_facility):
        await run(sa.text("INSERT INTO facilities (id, code, name, state_code) VALUES (:id, :c, 'Request Hospital', 'BR')"),
                  {"id": f, "c": f"R{uuid.uuid4().hex[:6].upper()}"})
    for uid, name, f in ((portal_user, "Guardian", fid), (desk_user, "Desk", fid), (doctor, "Dr Rao", fid),
                         (other_desk, "Other Desk", other_facility)):
        await run(sa.text("INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) VALUES (:u, :s, :n, :full, :f)"),
                  {"u": uid, "s": str(uuid.uuid4()), "n": f"u{uuid.uuid4().hex[:8]}", "full": name, "f": f})
    await run(sa.text("INSERT INTO departments (id, name, code, facility_id) VALUES (:d, 'Paediatrics', :c, :f)"),
              {"d": dept, "c": f"PED{uuid.uuid4().hex[:4]}", "f": fid})
    await run(sa.text("INSERT INTO departments (id, name, code, facility_id) VALUES (:d, 'Elsewhere', :c, :f)"),
              {"d": other_dept, "c": f"ELS{uuid.uuid4().hex[:4]}", "f": other_facility})
    await run(sa.text("INSERT INTO patients (id, full_name, sex, identity_path, facility_id, created_by, age_years, uhid) "
                      "VALUES (:p, 'Child Patient', 'other', 'demographics_only', :f, :u, 6, :h)"),
              {"p": patient, "f": fid, "u": desk_user, "h": f"IN-BR-{uuid.uuid4().hex[:10]}"})
    await db.flush()
    return SimpleNamespace(
        binding=SimpleNamespace(patient_id=patient, facility_id=fid),
        caller=SimpleNamespace(id=portal_user, facility_id=fid, roles=["patient"]),
        desk=SimpleNamespace(id=desk_user, facility_id=fid, roles=["receptionist"]),
        other_desk=SimpleNamespace(id=other_desk, facility_id=other_facility, roles=["receptionist"]),
        dept=dept, other_dept=other_dept, doctor=doctor,
    )


async def _ask(db, w, *, dept=None, on=TODAY + timedelta(days=3), tele=False, key=None):
    return await portal.request_appointment(
        portal.MyAppointmentRequestIn(department_id=dept or w.dept, preferred_date=on, session="morning",
                                      is_teleconsult=tele, reason="Fever for three days"),
        binding=w.binding, caller=w.caller, db=db, idempotency_key=key or str(uuid.uuid4()),
    )


async def test_a_request_is_booked_by_reception_and_the_patient_sees_the_time(db):
    w = await _world(db)
    asked = await _ask(db, w, tele=True)
    assert (asked.status, asked.department_name) == ("requested", "Paediatrics")
    waiting = await appointments_router.list_appointment_requests(current_user=w.desk, db=db, request_status="requested")
    assert [r.id for r in waiting] == [asked.id] and waiting[0].patient_name == "Child Patient"
    appointment = await appointments_router.confirm_appointment_request(
        asked.id, appointments_router.RequestConfirm(start_time="10:30", doctor_user_id=w.doctor),
        current_user=w.desk, db=db, idempotency_key=str(uuid.uuid4()),
    )
    assert appointment.is_teleconsult is True and appointment.start_time == "10:30"
    [mine] = await portal.my_appointment_requests(binding=w.binding, db=db)
    assert (mine.status, mine.start_time, mine.doctor_name) == ("confirmed", "10:30", "Dr Rao")
    # Teleconsult is stated honestly: HealthDoc books it but delivers no video.
    assert mine.teleconsult_status == "video_delivery_unavailable"
    with pytest.raises(HTTPException) as again:
        await appointments_router.confirm_appointment_request(
            asked.id, appointments_router.RequestConfirm(start_time="11:00"),
            current_user=w.desk, db=db, idempotency_key=str(uuid.uuid4()),
        )
    assert again.value.status_code == 409


async def test_a_declined_request_carries_the_reason_to_the_patient(db):
    w = await _world(db)
    asked = await _ask(db, w)
    with pytest.raises(HTTPException):
        await appointments_router.decline_appointment_request(
            asked.id, appointments_router.RequestDecline(reason=" "), current_user=w.desk, db=db,
            idempotency_key=str(uuid.uuid4()),
        )
    await appointments_router.decline_appointment_request(
        asked.id, appointments_router.RequestDecline(reason="No paediatrician that day; please choose Tuesday"),
        current_user=w.desk, db=db, idempotency_key=str(uuid.uuid4()),
    )
    [mine] = await portal.my_appointment_requests(binding=w.binding, db=db)
    assert mine.status == "declined" and "Tuesday" in mine.decline_reason


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("past", 422, "date_out_of_range"),
        ("too_far", 422, "date_out_of_range"),
        ("other_facility_department", 404, "department_not_found"),
    ],
)
async def test_a_request_is_refused_before_anything_is_stored(db, case, status, code):
    w = await _world(db)
    kwargs = {
        "past": {"on": TODAY - timedelta(days=1)},
        "too_far": {"on": TODAY + timedelta(days=61)},
        "other_facility_department": {"dept": w.other_dept},
    }[case]
    with pytest.raises(HTTPException) as refused:
        await _ask(db, w, **kwargs)
    assert (refused.value.status_code, refused.value.detail["code"]) == (status, code)


async def test_open_requests_are_capped_and_a_retry_does_not_add_one(db):
    w = await _world(db)
    first = await _ask(db, w, key="same-key")
    again = await _ask(db, w, key="same-key")
    assert first.id == again.id
    await _ask(db, w)
    await _ask(db, w)
    with pytest.raises(HTTPException) as refused:
        await _ask(db, w)
    assert refused.value.detail["code"] == "too_many_open_requests"


async def test_withdraw_once_and_other_facilities_cannot_act(db):
    w = await _world(db)
    asked = await _ask(db, w)
    with pytest.raises(HTTPException) as refused:
        await appointments_router.decline_appointment_request(
            asked.id, appointments_router.RequestDecline(reason="x"), current_user=w.other_desk, db=db,
            idempotency_key=str(uuid.uuid4()),
        )
    assert refused.value.status_code == 404
    out = await portal.withdraw_appointment_request(asked.id, binding=w.binding, db=db)
    assert out.status == "withdrawn"
    with pytest.raises(HTTPException) as again:
        await portal.withdraw_appointment_request(asked.id, binding=w.binding, db=db)
    assert again.value.status_code == 409
