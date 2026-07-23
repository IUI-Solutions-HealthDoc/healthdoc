"""Crypto helpers.

B2-W1-03 implements here:
  - aadhaar_blind_index(aadhaar: str) -> str   # HMAC-SHA256 keyed hash, hex
  - encrypt_pii(value: str) -> bytes           # AES-GCM via app key or pgcrypto
  - decrypt_pii(blob: bytes) -> str

Rules: Aadhaar is NEVER stored or logged in plaintext and is never a DB key.
Tests must prove no plaintext path (see tests/test_security.py stub).

Key rotation (schema v3.5, patient_identifiers.key_version):
  - New rows always get key_version = CURRENT_KEY_VERSION and are HMAC'd under
    the current key.
  - Lookups (duplicate-check search) must be tried under every ACTIVE key
    version until a background re-index job has moved all rows to the
    current version — see active_key_versions() / aadhaar_blind_indexes_all_versions().
  - Keys live only in env/secret manager, never in the DB or repo.
"""
import hashlib
import hmac
import json
import base64
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.common.config import get_settings

CURRENT_KEY_VERSION = 1  # code-level default; overridden by settings.aadhaar_hmac_current_key_version
_AES_KEY_LEN = 32       # AES-256
_NONCE_LEN = 12         # GCM standard nonce size   

def _load_hmac_keys() -> dict[int, str]:
    """Returns {key_version: key} for Aadhaar blind-index HMAC keys.

    Prefers aadhaar_hmac_keys_json (rotation-capable); falls back to the
    single legacy aadhaar_hmac_key as version 1 so existing .env files keep
    working unchanged.
    """
    settings = get_settings()

    if settings.aadhaar_hmac_keys_json:
        try:
            raw = json.loads(settings.aadhaar_hmac_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("aadhaar_hmac_keys_json is not valid JSON") from exc
        keys = {int(v): k for v, k in raw.items()}
        if not keys:
            raise ValueError("aadhaar_hmac_keys_json is set but empty")
        return keys

    return {1: settings.aadhaar_hmac_key}


def active_key_versions() -> list[int]:
    """All key versions currently loaded — used to search across old +
    new blind indexes during key rotation."""
    return sorted(_load_hmac_keys().keys())


def current_key_version() -> int:
    settings = get_settings()
    return settings.aadhaar_hmac_current_key_version


def aadhaar_blind_index(aadhaar: str, key_version: int | None = None) -> str:
    if not aadhaar or not aadhaar.isdigit() or len(aadhaar) != 12:
        raise ValueError("aadhaar_blind_index expects a 12-digit numeric Aadhaar string")

    version = key_version if key_version is not None else current_key_version()
    keys = _load_hmac_keys()

    if version not in keys:
        raise ValueError(f"No Aadhaar HMAC key configured for key_version={version}")

    key = keys[version].encode("utf-8")
    digest = hmac.new(key, aadhaar.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def aadhaar_blind_indexes_all_versions(aadhaar: str) -> dict[int, str]:
    """Compute the blind index under every active key version.

    Use for duplicate-check searches: WHERE identifier_blind_index IN (...)
    so a patient registered under an old key is still found even before
    the background re-index job has caught up.
    """
    return {v: aadhaar_blind_index(aadhaar, key_version=v) for v in active_key_versions()}


def _load_aes_keys() -> dict[int, bytes]:
    settings = get_settings()

    if settings.aadhaar_encryption_keys_json:
        try:
            raw = json.loads(settings.aadhaar_encryption_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("aadhaar_encryption_keys_json is not valid JSON") from exc
        keys = {int(v): base64.b64decode(k) for v, k in raw.items()}
        if not keys:
            raise ValueError("aadhaar_encryption_keys_json is set but empty")
        return keys

    derived = hashlib.sha256(settings.aadhaar_encryption_key.encode("utf-8")).digest()
    return {1: derived}

def encrypt_pii(value: str, key_version: int | None = None) -> bytes:
    """Encrypts a PII value (e.g. Aadhaar number) with AES-256-GCM.
    Blob layout: 1-byte key_version || 12-byte nonce || ciphertext+tag."""
    version = key_version if key_version is not None else current_key_version()
    keys = _load_aes_keys()

    if version not in keys:
        raise ValueError(f"No AES key configured for key_version={version}")
    if version > 255:
        raise ValueError("key_version must fit in a single byte (0-255)")

    aesgcm = AESGCM(keys[version])
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), associated_data=None)
    return bytes([version]) + nonce + ciphertext


def decrypt_pii(blob: bytes) -> str:
    if len(blob) < 1 + _NONCE_LEN + 16:
        raise ValueError("decrypt_pii: blob too short to be a valid ciphertext")

    version = blob[0]
    nonce = blob[1:1 + _NONCE_LEN]
    ciphertext = blob[1 + _NONCE_LEN:]

    keys = _load_aes_keys()
    if version not in keys:
        raise ValueError(f"No AES key configured for key_version={version}")

    aesgcm = AESGCM(keys[version])
    plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    return plaintext.decode("utf-8")