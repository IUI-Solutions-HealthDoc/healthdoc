"""B2-W1-02: UHID generation — Luhn check digit, sequence, lock key."""
import pytest

from app.patients.service import compute_check_digit, _advisory_lock_key


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


def test_advisory_lock_key_deterministic():
    a = _advisory_lock_key("IN-RJ-JPR001-2026-")
    b = _advisory_lock_key("IN-RJ-JPR001-2026-")
    assert a == b


def test_advisory_lock_key_differs_per_facility():
    a = _advisory_lock_key("IN-RJ-JPR001-2026-")
    b = _advisory_lock_key("IN-RJ-JPR002-2026-")
    assert a != b


def test_advisory_lock_key_within_postgres_int_range():
    key = _advisory_lock_key("IN-RJ-JPR001-2026-")
    assert 0 <= key < 2**31
