"""Ed25519 signing for audit log entries.

Schema doc §3-0003 / architecture doc §27.6: all audit log entries are
signed with Ed25519 at write time. This module loads (or, in dev only,
generates) the signing key and exposes a sign() helper used by
app.audit.service.write_audit_log().

PRODUCTION NOTE: audit_signing_key_b64 must be set via real secrets
management (not .env in plaintext) before go-live. The dev-ephemeral
fallback below generates a new key on every process start, which means
signatures are NOT verifiable across restarts — this is intentional and
acceptable for local dev/tests only. Hardware-backed key storage (TEE/
HSM, per architecture doc §27.3) is out of scope for this change and
tracked separately.
"""
import base64
import logging

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.common.config import get_settings

log = logging.getLogger("healthdoc.audit")

_cached_key: Ed25519PrivateKey | None = None


def _load_or_generate_key() -> Ed25519PrivateKey:
    settings = get_settings()
    if settings.audit_signing_key_b64:
        seed = base64.b64decode(settings.audit_signing_key_b64)
        return Ed25519PrivateKey.from_private_bytes(seed)

    log.warning(
        "AUDIT_SIGNING_KEY_B64 not set — generating an ephemeral Ed25519 "
        "key for this process only. Signatures will NOT be verifiable "
        "across restarts. This is only acceptable in dev/test."
    )
    return Ed25519PrivateKey.generate()


def get_signing_key() -> Ed25519PrivateKey:
    global _cached_key
    if _cached_key is None:
        _cached_key = _load_or_generate_key()
    return _cached_key


def sign(payload_bytes: bytes) -> str:
    """Sign payload_bytes, return base64-encoded signature."""
    key = get_signing_key()
    signature = key.sign(payload_bytes)
    return base64.b64encode(signature).decode("ascii")


def get_signer_key_id() -> str:
    return get_settings().audit_signer_key_id
