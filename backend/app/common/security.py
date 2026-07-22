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

from app.common.config import get_settings

CURRENT_KEY_VERSION = 1  # code-level default; overridden by settings.aadhaar_hmac_current_key_version


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


def encrypt_pii(value: str) -> bytes:  # pragma: no cover — not in B2-W1-03 scope
    raise NotImplementedError


def decrypt_pii(blob: bytes) -> str:  # pragma: no cover — not in B2-W1-03 scope
    raise NotImplementedError