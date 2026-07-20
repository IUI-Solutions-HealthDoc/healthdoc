"""B2-W1-03: aadhaar_blind_index — no plaintext path, deterministic, keyed."""
import pytest

from app.common.security import aadhaar_blind_index


def test_blind_index_is_deterministic():
    a = aadhaar_blind_index("999999990019")
    b = aadhaar_blind_index("999999990019")
    assert a == b


def test_blind_index_differs_for_different_input():
    a = aadhaar_blind_index("999999990019")
    b = aadhaar_blind_index("999999990020")
    assert a != b


def test_blind_index_is_64_char_hex():
    result = aadhaar_blind_index("999999990019")
    assert len(result) == 64
    int(result, 16)  # raises ValueError if not valid hex


def test_blind_index_rejects_wrong_length():
    with pytest.raises(ValueError):
        aadhaar_blind_index("12345")


def test_blind_index_rejects_non_numeric():
    with pytest.raises(ValueError):
        aadhaar_blind_index("99999999001x")


def test_blind_index_never_contains_plaintext_input():
    aadhaar = "999999990019"
    result = aadhaar_blind_index(aadhaar)
    assert aadhaar not in result
