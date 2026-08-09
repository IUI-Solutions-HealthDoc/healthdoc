"""B2-W1-02: UHID generation — Luhn check digit, Postgres sequence naming."""
import pytest

from app.patients.service import compute_check_digit, _sequence_name, _extract_digits, validate_uhid


def test_check_digit_is_single_digit():
    result = compute_check_digit("000042")
    assert len(result) == 1
    assert result.isdigit()


def test_check_digit_deterministic():
    a = compute_check_digit("000042")
    b = compute_check_digit("000042")
    assert a == b


def test_check_digit_rejects_invalid_characters():
    with pytest.raises(ValueError):
        compute_check_digit("00004@")


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


def test_validate_uhid_accepts_a_correctly_generated_uhid():
    body = "IN-RJ-JPR001-2026-000042"
    check_digit = compute_check_digit(_extract_digits(body))
    assert validate_uhid(f"{body}-{check_digit}") is True


def test_validate_uhid_catches_a_mistyped_state_code():
    # Letters are encoded as 10-35 (A=10, B=11, ..., Z=35) before
    # checksumming (should-fix, PR review), so a state-code typo (RJ->MP)
    # changes the checksummed digit string and is caught — not a limitation
    # anymore. Full coverage: facility typos, state typos, all get caught.
    body = "IN-RJ-JPR001-2026-000042"
    check_digit = compute_check_digit(_extract_digits(body))
    tampered = f"IN-MP-JPR001-2026-000042-{check_digit}"
    assert validate_uhid(tampered) is False


def test_validate_uhid_rejects_a_mistyped_facility_code():
    body = "IN-RJ-JPR001-2026-000042"
    check_digit = compute_check_digit(_extract_digits(body))
    tampered = f"IN-RJ-JPR002-2026-000042-{check_digit}"
    assert validate_uhid(tampered) is False


def test_validate_uhid_rejects_wrong_check_digit():
    assert validate_uhid("IN-RJ-JPR001-2026-000042-9") is False


def test_validate_uhid_rejects_malformed_string():
    assert validate_uhid("not-a-uhid-at-all") is False
    assert validate_uhid("") is False
