"""Crypto helpers.

B2-W1-03 implements here:
  - aadhaar_blind_index(aadhaar: str) -> str   # HMAC-SHA256 keyed hash, hex
  - encrypt_pii(value: str) -> tuple[bytes, int]  # AES-GCM via app key, returns (ciphertext, key_version)
  - decrypt_pii(blob: bytes, key_version: int) -> str
Rules: Aadhaar is NEVER stored or logged in plaintext and is never a DB key.
Tests must prove no plaintext path (see tests/test_security.py stub).

<<<<<<< HEAD
ABHA linking token uses the SAME encrypt_pii / decrypt_pii — do not create a
second implementation (B1-W3-02).

KEY MANAGEMENT:
  - Keys are read from Settings (common/config.py), never os.environ directly.
  - The app REFUSES TO START if either key is missing, still the placeholder,
    or under 32 bytes of entropy. Fail loudly at boot, not quietly at rest.
  - Keys must be base64-encoded 32 random bytes.
  - Generate a key: python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
=======
Key rotation (schema v3.5, patient_identifiers.key_version):
  - New rows always get the current key version (see current_hmac_key_version /
    current_aes_key_version below) and are HMAC'd / encrypted under it.
  - Lookups (duplicate-check search) must be tried under every ACTIVE key
    version until a background re-index job has moved all rows to the
    current version — see active_key_versions() / aadhaar_blind_indexes_all_versions().
  - Keys live only in env/secret manager, never in the DB or repo.
>>>>>>> 4771ce7 (fix: address all PR review blockers and should-fixes (B2 patients module))
"""
import base64
import hashlib
import hmac
import os
from functools import lru_cache

from app.common.config import get_settings

<<<<<<< HEAD
# Current key version — increment on rotation, never decrement.
_CURRENT_KEY_VERSION = 1
=======
_AES_KEY_LEN = 32       # AES-256
_NONCE_LEN = 12         # GCM standard nonce size   
>>>>>>> 4771ce7 (fix: address all PR review blockers and should-fixes (B2 patients module))

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


def aadhaar_blind_index(aadhaar: str) -> str:
    """HMAC-SHA256 keyed hash, hex. Aadhaar never stored in plaintext."""
    key = _get_hmac_key()
    return hmac.new(key, aadhaar.encode(), hashlib.sha256).hexdigest()


def encrypt_pii(value: str) -> tuple[bytes, int]:
    """AES-256-GCM encryption. Returns (nonce+ciphertext+tag, key_version).

    Layout: 12-byte nonce || ciphertext || 16-byte tag
    Key version is returned so rotation works without big-bang re-encrypt.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    return nonce + ct, _CURRENT_KEY_VERSION


def decrypt_pii(blob: bytes, key_version: int = _CURRENT_KEY_VERSION) -> str:
    """Decrypt an AES-256-GCM blob using the currently loaded key version."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

<<<<<<< HEAD
    if key_version != _CURRENT_KEY_VERSION:
        raise CryptoConfigError(
            f"Ciphertext was written with key version {key_version}, but only "
            f"{_CURRENT_KEY_VERSION} is loaded. Key rotation needs a version-to-key map "
            "before any key is rotated."
        )
    key = _get_encryption_key()
    nonce = blob[:12]
    ciphertext_and_tag = blob[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext_and_tag, None).decode("utf-8")
=======

def current_hmac_key_version() -> int:
    return get_settings().aadhaar_hmac_current_key_version


def current_aes_key_version() -> int:
    """Separate from the HMAC version pointer (PR review blocker 7) — see
    config.py's aadhaar_encryption_current_key_version docstring."""
    return get_settings().aadhaar_encryption_current_key_version


def aadhaar_blind_index(aadhaar: str, key_version: int | None = None) -> str:
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

    # Blocker 2 fix: aadhaar_encryption_key is validated at settings load
    # (config.py) to already BE base64-encoded random bytes — decode
    # directly, no KDF. A SHA-256 of a human passphrase is brute-forceable
    # at hash speed; this key must already carry full entropy on its own.
    decoded = base64.b64decode(settings.aadhaar_encryption_key)
    return {1: decoded}

def encrypt_pii(
    value: str, key_version: int | None = None, associated_data: bytes | None = None,
) -> bytes:
    """Encrypts a PII value (e.g. Aadhaar number) with AES-256-GCM.
    Blob layout: 1-byte key_version || 12-byte nonce || ciphertext+tag.

    associated_data (should-fix, PR review): binds the ciphertext to the row
    it belongs to (e.g. f"{patient_id}:{identifier_type}"). Without this, a
    ciphertext blob copied from one row into another decrypts cleanly under
    that row's key — GCM authenticates the bytes, not which row they came
    from. The caller must pass the same associated_data to decrypt_pii, or
    decryption fails (by design: it means the blob is in the wrong row)."""
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
    """associated_data must match exactly what was passed to encrypt_pii for
    this blob, or decryption raises (cryptography's AESGCM raises
    InvalidTag, not ValueError — callers checking for ValueError only should
    catch both, or catch Exception, around this call)."""
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
>>>>>>> 4771ce7 (fix: address all PR review blockers and should-fixes (B2 patients module))
