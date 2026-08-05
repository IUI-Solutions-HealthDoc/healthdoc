"""Crypto helpers.

B2-W1-03 implements here:
  - aadhaar_blind_index(aadhaar: str) -> str   # HMAC-SHA256 keyed hash, hex
  - encrypt_pii(value: str) -> tuple[bytes, int]  # AES-GCM via app key, returns (ciphertext, key_version)
  - decrypt_pii(blob: bytes, key_version: int) -> str
Rules: Aadhaar is NEVER stored or logged in plaintext and is never a DB key.
Tests must prove no plaintext path (see tests/test_security.py stub).
"""

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from app.common.config import get_settings

_CURRENT_KEY_VERSION = 1
_PLACEHOLDERS = frozenset({
    "change-me", "change-me-healthdoc-pii-key-v1", "change-me-aadhaar-hmac-key",
    "", "placeholder", "test", "dev",
})


class CryptoConfigError(RuntimeError):
    """Raised at boot if crypto keys are missing or insecure."""


def _validate_key(value: str, name: str) -> bytes:
    """Validate and decode a base64-encoded key.

    Raises CryptoConfigError if the key is missing, a known placeholder, or invalid.
    """
    if not value or value.strip().lower() in _PLACEHOLDERS:
        raise CryptoConfigError(
            f"{name} is missing or still set to a placeholder. "
            f"Generate a real key: python3 -c "
            f"\"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        raw = base64.b64decode(value)
    except Exception:
        raise CryptoConfigError(
            f"{name} is not valid base64. Keys must be base64-encoded 32 random bytes."
        )
    if len(raw) < 32:
        raise CryptoConfigError(
            f"{name} is only {len(raw)} bytes after decoding; minimum is 32. "
            f"Generate a real key: python3 -c "
            f"\"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    return raw


@lru_cache
def _get_encryption_key() -> bytes:
    settings = get_settings()
    return _validate_key(settings.pii_encryption_key, "PII_ENCRYPTION_KEY")


@lru_cache
def _get_hmac_key() -> bytes:
    settings = get_settings()
    return _validate_key(settings.aadhaar_hmac_key, "AADHAAR_HMAC_KEY")


def aadhaar_blind_index(aadhaar: str) -> str:
    """HMAC-SHA256 keyed hash, hex. Aadhaar never stored in plaintext."""
    key = _get_hmac_key()
    return hmac.new(key, aadhaar.encode(), hashlib.sha256).hexdigest()


def encrypt_pii(value: str) -> tuple[bytes, int]:
    """AES-256-GCM encryption. Returns (nonce+ciphertext+tag, key_version)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    return nonce + ct, _CURRENT_KEY_VERSION


def decrypt_pii(blob: bytes, key_version: int = _CURRENT_KEY_VERSION) -> str:
    """Decrypt AES-256-GCM blob. key_version allows old-key lookups on rotation."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key()
    nonce = blob[:12]
    ciphertext_and_tag = blob[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext_and_tag, None).decode("utf-8")
