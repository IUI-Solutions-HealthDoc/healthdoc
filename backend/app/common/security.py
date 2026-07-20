"""Crypto helpers.

B2-W1-03 implements here:
  - aadhaar_blind_index(aadhaar: str) -> str   # HMAC-SHA256 keyed hash, hex
  - encrypt_pii(value: str) -> bytes           # AES-GCM via app key or pgcrypto
  - decrypt_pii(blob: bytes) -> str

Rules: Aadhaar is NEVER stored or logged in plaintext and is never a DB key.
Tests must prove no plaintext path (see tests/test_security.py stub).
"""
import hashlib
import hmac

from app.common.config import get_settings

CURRENT_KEY_VERSION = 1


def aadhaar_blind_index(aadhaar: str, key_version: int = CURRENT_KEY_VERSION) -> str:
    if not aadhaar or not aadhaar.isdigit() or len(aadhaar) != 12:
        raise ValueError("aadhaar_blind_index expects a 12-digit numeric Aadhaar string")

    settings = get_settings()
    key = settings.aadhaar_hmac_key.encode("utf-8")

    digest = hmac.new(key, aadhaar.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def encrypt_pii(value: str) -> bytes:  # pragma: no cover — not in B2-W1-03 scope
    raise NotImplementedError


def decrypt_pii(blob: bytes) -> str:  # pragma: no cover — not in B2-W1-03 scope
    raise NotImplementedError
