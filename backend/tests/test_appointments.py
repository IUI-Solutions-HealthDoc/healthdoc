"""HD-11: Appointments, scheduling, conflict prevention, and service catalogue tests."""

import uuid
from datetime import date
import pytest
from pydantic import ValidationError

from app.appointments.schemas import (
    AppointmentCheckInRequest,
    AppointmentCheckInResult,
    AppointmentCreate,
    AppointmentServiceCreate,
    AppointmentUpdate,
)
from app.appointments.service import calc_end_time


def test_calc_end_time_within_hour():
    assert calc_end_time("09:00", 15) == "09:15"
    assert calc_end_time("09:30", 20) == "09:50"


def test_calc_end_time_crossing_hour():
    assert calc_end_time("09:45", 30) == "10:15"
    assert calc_end_time("11:50", 25) == "12:15"


def test_appointment_service_create_validation():
    # Valid
    svc = AppointmentServiceCreate(name="General Consultation", duration_minutes=20)
    assert svc.name == "General Consultation"
    assert svc.duration_minutes == 20

    # Invalid duration (< 5 or > 240)
    with pytest.raises(ValidationError):
        AppointmentServiceCreate(name="Invalid", duration_minutes=3)

    with pytest.raises(ValidationError):
        AppointmentServiceCreate(name="Invalid", duration_minutes=300)


def test_appointment_create_validation():
    p_id = uuid.uuid4()
    d_id = uuid.uuid4()

    # Valid
    appt = AppointmentCreate(
        patient_id=p_id,
        department_id=d_id,
        appointment_date=date(2026, 10, 1),
        start_time="10:30",
        duration_minutes=30,
        is_walk_in=True,
    )
    assert appt.start_time == "10:30"
    assert appt.is_walk_in is True
    assert appt.is_teleconsult is False

    # Invalid time format
    with pytest.raises(ValidationError):
        AppointmentCreate(
            patient_id=p_id,
            department_id=d_id,
            appointment_date=date(2026, 10, 1),
            start_time="10-30",
        )


def test_appointment_teleconsult_flag():
    p_id = uuid.uuid4()
    d_id = uuid.uuid4()
    appt = AppointmentCreate(
        patient_id=p_id,
        department_id=d_id,
        appointment_date=date(2026, 10, 1),
        start_time="14:00",
        is_teleconsult=True,
    )
    assert appt.is_teleconsult is True


def test_appointment_check_in_schemas():
    appt_id = uuid.uuid4()
    visit_id = uuid.uuid4()
    token_id = uuid.uuid4()

    req = AppointmentCheckInRequest(priority="urgent")
    assert req.priority == "urgent"

    res = AppointmentCheckInResult(
        appointment_id=appt_id,
        status="checked_in",
        visit_id=visit_id,
        visit_number="VIS-20261001-0001",
        token_id=token_id,
        token_display="MED-005",
    )
    assert res.status == "checked_in"
    assert res.visit_number == "VIS-20261001-0001"
    assert res.token_display == "MED-005"
