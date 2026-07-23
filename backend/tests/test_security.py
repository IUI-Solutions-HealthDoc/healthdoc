"""B2-W1-03: aadhaar_blind_index — no plaintext path, deterministic, keyed."""
import json

import pytest

from app.common.security import (
    aadhaar_blind_index,
    aadhaar_blind_indexes_all_versions,
    active_key_versions,
)
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

def test_default_active_key_versions_is_just_version_1(monkeypatch):
    from app.common.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("AADHAAR_HMAC_KEYS_JSON", "")
    assert active_key_versions() == [1]
    get_settings.cache_clear()


def test_rotation_produces_different_hash_per_version(monkeypatch):
    from app.common.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv(
        "AADHAAR_HMAC_KEYS_JSON",
        json.dumps({"1": "old-key-value", "2": "new-key-value"}),
    )
    aadhaar = "999999990019"
    v1 = aadhaar_blind_index(aadhaar, key_version=1)
    v2 = aadhaar_blind_index(aadhaar, key_version=2)
    assert v1 != v2
    assert active_key_versions() == [1, 2]
    get_settings.cache_clear()


def test_lookup_across_all_versions_includes_both(monkeypatch):
    from app.common.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv(
        "AADHAAR_HMAC_KEYS_JSON",
        json.dumps({"1": "old-key-value", "2": "new-key-value"}),
    )
    aadhaar = "999999990019"
    all_versions = aadhaar_blind_indexes_all_versions(aadhaar)
    assert set(all_versions.keys()) == {1, 2}
    assert all_versions[1] != all_versions[2]
    get_settings.cache_clear()


def test_unconfigured_key_version_raises():
    with pytest.raises(ValueError):
        aadhaar_blind_index("999999990019", key_version=99)