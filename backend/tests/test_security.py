"""Tests for common/security.py — proves no plaintext path for Aadhaar."""
import base64
import os

import pytest


@pytest.fixture(autouse=True)
def _set_crypto_keys(monkeypatch):
    """Provide valid base64-encoded 32-byte keys for all tests."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)
    monkeypatch.setenv("AADHAAR_HMAC_KEY", key)
    # Clear lru_cache between tests
    from app.common.config import get_settings
    from app.common.security import _get_encryption_key, _get_hmac_key
    get_settings.cache_clear()
    _get_encryption_key.cache_clear()
    _get_hmac_key.cache_clear()


def test_blind_index_deterministic():
    """Same Aadhaar → same blind index, every time."""
    from app.common.security import aadhaar_blind_index
    idx1 = aadhaar_blind_index("123456789012")
    idx2 = aadhaar_blind_index("123456789012")
    assert idx1 == idx2


def test_blind_index_different_inputs_differ():
    """Different Aadhaar numbers produce different blind indexes."""
    from app.common.security import aadhaar_blind_index
    idx_a = aadhaar_blind_index("123456789012")
    idx_b = aadhaar_blind_index("999988887777")
    assert idx_a != idx_b


def test_blind_index_no_plaintext():
    """The raw Aadhaar never appears in the output."""
    from app.common.security import aadhaar_blind_index
    aadhaar = "123456789012"
    idx = aadhaar_blind_index(aadhaar)
    assert aadhaar not in idx


def test_encrypt_decrypt_roundtrip():
    """encrypt_pii + decrypt_pii returns the original value.

    encrypt_pii returns ONE value now, not (blob, key_version): the version is
    the first byte of the blob itself, so it travels with the ciphertext and a
    caller cannot store the two apart and lose the pairing. decrypt_pii reads
    it back out — its second parameter is associated_data, not the version.
    """
    from app.common.security import encrypt_pii, decrypt_pii
    plaintext = "sensitive-token-12345"
    blob = encrypt_pii(plaintext)
    assert blob[0] >= 1  # key_version, embedded
    assert plaintext.encode() not in blob  # no plaintext in ciphertext
    decrypted = decrypt_pii(blob)
    assert decrypted == plaintext


def test_encrypt_binds_to_associated_data():
    """A blob encrypted for one row must not decrypt as another row's.

    GCM authenticates the bytes, not the row they came from — associated_data
    is what makes a copied ciphertext fail instead of decrypting cleanly.
    """
    import pytest
    from cryptography.exceptions import InvalidTag
    from app.common.security import encrypt_pii, decrypt_pii
    blob = encrypt_pii("1234-5678-9012", associated_data=b"patient-a:aadhaar")
    assert decrypt_pii(blob, associated_data=b"patient-a:aadhaar") == "1234-5678-9012"
    with pytest.raises(InvalidTag):
        decrypt_pii(blob, associated_data=b"patient-b:aadhaar")


def test_encrypt_no_plaintext_in_blob():
    """The plaintext value never appears in the encrypted blob."""
    from app.common.security import encrypt_pii
    plaintext = "patient-aadhaar-data-very-secret"
    blob = encrypt_pii(plaintext)
    assert plaintext.encode() not in blob


def test_placeholder_key_rejected():
    """The default 'change-me' key must be rejected."""
    from app.common.security import _validate_key, CryptoConfigError
    with pytest.raises(CryptoConfigError):
        _validate_key("change-me", "TEST_KEY")


def test_short_key_rejected():
    """A key under 32 bytes must be rejected."""
    from app.common.security import _validate_key, CryptoConfigError
    short = base64.b64encode(os.urandom(16)).decode()  # only 16 bytes
    with pytest.raises(CryptoConfigError):
        _validate_key(short, "TEST_KEY")


def test_non_aes_key_length_rejected():
    """Keys that AES-GCM would reject must fail during validation."""
    from app.common.security import _validate_key, CryptoConfigError
    invalid = base64.b64encode(os.urandom(40)).decode()
    with pytest.raises(CryptoConfigError):
        _validate_key(invalid, "TEST_KEY")
