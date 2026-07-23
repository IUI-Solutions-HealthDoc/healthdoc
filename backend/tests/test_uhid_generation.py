"""B2-W1-02: UHID generation — Luhn check digit, Postgres sequence naming."""
import pytest

from app.patients.service import compute_check_digit, _sequence_name


def test_check_digit_is_single_digit():
    result = compute_check_digit("000042")
    assert len(result) == 1
    assert result.isdigit()


def test_check_digit_deterministic():
    a = compute_check_digit("000042")
    b = compute_check_digit("000042")
    assert a == b


def test_check_digit_rejects_non_numeric():
    with pytest.raises(ValueError):
        compute_check_digit("00004x")


def test_sequence_name_format():
    assert _sequence_name("JPR001", 2026) == "seq_uhid_jpr001_2026"


def test_sequence_name_differs_per_facility():
    a = _sequence_name("JPR001", 2026)
    b = _sequence_name("JPR002", 2026)
    assert a != b


def test_sequence_name_differs_per_year():
    a = _sequence_name("JPR001", 2026)
    b = _sequence_name("JPR001", 2027)
    assert a != b


def test_sequence_name_rejects_invalid_facility_code():
    with pytest.raises(ValueError):
        _sequence_name("JPR001; DROP TABLE patients;--", 2026)