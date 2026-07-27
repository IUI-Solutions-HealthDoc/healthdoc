"""emergency/ module — THID generation tests (no formal ticket yet; pure-logic only,
mirrors test_uhid_generation.py's style)."""
import pytest

from app.emergency.service import _thid_sequence_name, _current_day_str


def test_thid_sequence_name_format():
    name = _thid_sequence_name("JPR001", "260714")
    assert name == "seq_thid_jpr001_260714"


def test_thid_sequence_name_differs_per_facility():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("DEL002", "260714")
    assert a != b


def test_thid_sequence_name_differs_per_day():
    a = _thid_sequence_name("JPR001", "260714")
    b = _thid_sequence_name("JPR001", "260715")
    assert a != b


def test_thid_sequence_name_rejects_invalid_facility_code():
    with pytest.raises(ValueError):
        _thid_sequence_name("JPR001; DROP TABLE patients;--", "260714")


def test_current_day_str_is_six_digits():
    result = _current_day_str()
    assert len(result) == 6
    int(result)  # raises ValueError if not numeric
