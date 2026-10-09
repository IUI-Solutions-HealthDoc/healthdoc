"""Business dates come from the facility's calendar, not the server's UTC one.

The server runs on UTC, so between midnight and 05:30 IST its date is still
yesterday's. A child born just after midnight in an Indian ward had a date of
birth "in the future"; ages, KPI windows and immunization due dates were all a
day behind for those hours.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.common import business_date
from app.patients.schemas import PatientCreate
from app.queue.service import _patient_age
from app.reports.router import _window

# 20:00 UTC on 30 September is 01:30 IST on 1 October.
_UTC_EVENING = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _UTC_EVENING.astimezone(tz) if tz else _UTC_EVENING.replace(tzinfo=None)


@pytest.fixture
def utc_evening(monkeypatch):
    monkeypatch.setattr(business_date, "datetime", _FrozenDatetime)


def test_an_indian_today_is_not_a_future_date_of_birth(utc_evening):
    patient = PatientCreate(full_name="Newborn Test", sex="female", dob=date(2026, 10, 1))
    assert patient.dob == date(2026, 10, 1)


def test_a_date_beyond_every_timezone_is_still_refused(utc_evening):
    with pytest.raises(ValidationError, match="dob cannot be in the future"):
        PatientCreate(full_name="Newborn Test", sex="female", dob=date(2026, 10, 2))


def test_latest_date_anywhere_is_utc_plus_fourteen(utc_evening):
    assert business_date.latest_date_anywhere() == date(2026, 10, 1)


def test_age_from_dob_uses_the_supplied_facility_day():
    dob = date(2000, 10, 1)
    assert _patient_age(dob, None, date(2026, 9, 30)) == 25
    assert _patient_age(dob, None, date(2026, 10, 1)) == 26


def test_recorded_age_wins_over_dob():
    assert _patient_age(date(2000, 1, 1), 7, date(2026, 10, 1)) == 7


def test_report_window_ends_on_the_facility_day():
    today = date(2026, 10, 1)
    assert _window("weekly", None, None, today) == (date(2026, 9, 24), today)
    explicit = (date(2026, 1, 1), date(2026, 1, 31))
    assert _window("weekly", *explicit, today) == explicit
