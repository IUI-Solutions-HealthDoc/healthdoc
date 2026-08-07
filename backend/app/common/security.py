"""Crypto helpers.

B2-W1-03 implements here:
  - aadhaar_blind_index(aadhaar: str) -> str   # HMAC-SHA256 keyed hash, hex
  - encrypt_pii(value: str) -> bytes           # AES-GCM, blob layout: version_byte || nonce || ciphertext+tag
  - decrypt_pii(blob: bytes) -> str

Key rotation (schema v3.5, patient_identifiers.key_version):
  - New rows always get the current key version (see current_hmac_key_version /
    current_aes_key_version below) and are HMAC'd / encrypted under it.
  - Lookups (duplicate-check search) must be tried under every ACTIVE key
    version until a background re-index job has moved all rows to the
    current version — see active_key_versions() / aadhaar_blind_indexes_all_versions().
  - Keys live only in env/secret manager, never in the DB or repo.

ABHA linking token uses the SAME encrypt_pii / decrypt_pii — do not create a
second implementation (B1-W3-02).

KEY MANAGEMENT:
  - Keys are read from Settings (common/config.py), never os.environ directly.
  - The app REFUSES TO START if either key is missing, still the placeholder,
    or under 32 bytes of entropy. Fail loudly at boot, not quietly at rest.
  - Keys must be base64-encoded 32 random bytes.
  - Generate a key: python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
"""
import base64
import hashlib
import hmac
import json
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.common.config import get_settings

_AES_KEY_LEN = 32       # AES-256
_NONCE_LEN = 12         # GCM standard nonce size

# Placeholder values that MUST be replaced before production use.
_PLACEHOLDERS = frozenset({
    "change-me", "change-me-healthdoc-pii-key-v1", "change-me-aadhaar-hmac-key",
    "", "placeholder", "test", "dev",
})


class CryptoConfigError(RuntimeError):
    """Raised at boot if crypto keys are missing or insecure."""


def _validate_key(value: str, name: str) -> bytes:
    """Validate and decode a base64-encoded key. Raises CryptoConfigError if
    the key is missing, a known placeholder, or under 32 bytes of entropy."""
    if not value or value.strip().lower() in _PLACEHOLDERS:
        raise CryptoConfigError(
            f"{name} is missing or still set to a placeholder. "
            f"Generate a real key: python3 -c "
            f"\"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise CryptoConfigError(
            f"{name} is not valid base64. "
            f"Keys must be base64-encoded 32 random bytes."
        )
    if len(raw) != 32:
        raise CryptoConfigError(
            f"{name} decodes to {len(raw)} bytes; AES-256-GCM requires exactly 32. "
            f"Generate a real key: python3 -c "
            f"\"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    return raw


@lru_cache
def _get_encryption_key() -> bytes:
    """Load and validate the PII encryption key from settings.
    Fails loudly at first call if the key is insecure."""
    settings = get_settings()
    return _validate_key(settings.pii_encryption_key, "PII_ENCRYPTION_KEY")


@lru_cache
def _get_hmac_key() -> bytes:
    """Load and validate the Aadhaar HMAC key from settings.
    Fails loudly at first call if the key is insecure."""
    settings = get_settings()
    return _validate_key(settings.aadhaar_hmac_key, "AADHAAR_HMAC_KEY")


def current_hmac_key_version() -> int:
    return get_settings().aadhaar_hmac_current_key_version


def current_aes_key_version() -> int:
    """Separate from the HMAC version pointer (PR review blocker 7) — see
    config.py's aadhaar_encryption_current_key_version docstring."""
    return get_settings().aadhaar_encryption_current_key_version


def active_key_versions() -> list[int]:
    """All HMAC key versions that may have been used to index existing rows."""
    keys = _load_hmac_keys()
    return sorted(keys.keys())


def _load_hmac_keys() -> dict[int, str]:
    settings = get_settings()
    if hasattr(settings, "aadhaar_hmac_keys_json") and settings.aadhaar_hmac_keys_json:
        try:
            raw = json.loads(settings.aadhaar_hmac_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("aadhaar_hmac_keys_json is not valid JSON") from exc
        return {int(v): k for v, k in raw.items()}
    return {1: settings.aadhaar_hmac_key}


def _load_aes_keys() -> dict[int, bytes]:
    settings = get_settings()
    if hasattr(settings, "aadhaar_encryption_keys_json") and settings.aadhaar_encryption_keys_json:
        try:
            raw = json.loads(settings.aadhaar_encryption_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("aadhaar_encryption_keys_json is not valid JSON") from exc
        keys = {int(v): base64.b64decode(k) for v, k in raw.items()}
        if not keys:
            raise ValueError("aadhaar_encryption_keys_json is set but empty")
        return keys
    return {1: _get_encryption_key()}


def aadhaar_blind_index(aadhaar: str, key_version: int | None = None) -> str:
    """HMAC-SHA256 keyed hash, hex. Aadhaar never stored in plaintext."""
    if not aadhaar or not aadhaar.isdigit() or len(aadhaar) != 12:
        raise ValueError("aadhaar_blind_index expects a 12-digit numeric Aadhaar string")

    version = key_version if key_version is not None else current_hmac_key_version()
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


def encrypt_pii(
    value: str, key_version: int | None = None, associated_data: bytes | None = None,
) -> bytes:
    """Encrypts a PII value with AES-256-GCM.
    Blob layout: 1-byte key_version || 12-byte nonce || ciphertext+tag.

    associated_data binds the ciphertext to the row it belongs to
    (e.g. f"{patient_id}:{identifier_type}"). Without this, a ciphertext
    blob copied from one row into another decrypts cleanly — GCM authenticates
    the bytes, not which row they came from. Pass the same associated_data
    to decrypt_pii or decryption fails (by design).
    """
    version = key_version if key_version is not None else current_aes_key_version()
    keys = _load_aes_keys()

    if version not in keys:
        raise ValueError(f"No AES key configured for key_version={version}")
    if version > 255:
        raise ValueError("key_version must fit in a single byte (0-255)")

    aesgcm = AESGCM(keys[version])
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), associated_data=associated_data)
    return bytes([version]) + nonce + ciphertext


def decrypt_pii(blob: bytes, associated_data: bytes | None = None) -> str:
    """Decrypt an AES-256-GCM blob.

    associated_data must match exactly what was passed to encrypt_pii for
    this blob, or decryption raises InvalidTag.
    """
    if len(blob) < 1 + _NONCE_LEN + 16:
        raise ValueError("decrypt_pii: blob too short to be a valid ciphertext")

    version = blob[0]
    nonce = blob[1:1 + _NONCE_LEN]
    ciphertext = blob[1 + _NONCE_LEN:]

    keys = _load_aes_keys()
    if version not in keys:
        raise ValueError(f"No AES key configured for key_version={version}")

    aesgcm = AESGCM(keys[version])
    plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=associated_data)
    return plaintext.decode("utf-8")
