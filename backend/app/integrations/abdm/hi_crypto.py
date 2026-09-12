"""Health-information transfer crypto for ABDM (M2/M3 key handling).

This is the file a WASA assessor opens when the scope says "HIP/HIU key
handling", so it is written to be read rather than to be clever.

WHAT ABDM SPECIFIES, AND WHY EACH CHOICE IS NOT THE OTHER ONE
-------------------------------------------------------------
A health-information payload never travels encrypted-to-the-gateway. The HIU
publishes an ephemeral public key and a nonce in its request; the HIP generates
its own ephemeral pair and nonce, derives a shared key, encrypts the FHIR
bundle, and pushes the ciphertext straight to the HIU's data endpoint. The
gateway brokers the request and never holds a key that opens the payload.

  curve      Bouncy Castle's named Curve25519 with full EC points, as used by
             Fidelius. This is NOT RFC7748's raw 32-byte X25519 wire format.
             EC operations are delegated to the pinned local Java helper.
  kdf        HKDF-SHA256 over the raw ECDH output. The raw ECDH result must
             never be used as an AES key directly — it is a curve point, not
             uniformly random, and AES-GCM assumes a uniform key.
  salt/iv    Derived from the XOR of BOTH nonces, so neither party alone fixes
             the IV. First 20 bytes are the HKDF salt, last 12 are the GCM IV.
             This is the shape ABDM's reference implementations use.
  cipher     AES-256-GCM. Authenticated: a tampered ciphertext fails to open
             rather than decrypting to plausible-looking clinical data, which
             is the entire point for a health record.

WHERE THE PRIVATE KEY LIVES, AND WHY THE TWO SIDES DIFFER
---------------------------------------------------------
`generate_key_material()` hands the private key back to the caller and keeps no
copy. This module writes a private key to nothing — no table, no log, no
response body. What the two callers then do with it is not symmetric, and the
asymmetry is real rather than an oversight:

  HIP  encrypts and pushes within the same request it was asked in, so its
       keypair never outlives the call stack. Nothing persists it.
  HIU  publishes its public half in a request and then waits — the HIP may push
       minutes or hours later, into a different process. Its private key has to
       survive that gap or the data it asked for cannot be opened.

So the HIU persists its private key ENCRYPTED (common/security.py, AES-GCM,
key-versioned) against the transfer row, and clears it once the transfer
completes or expires. That is a deliberate trade, not a lapse: the alternative
is holding it in memory and losing every in-flight request on a deploy, which
in practice produces a retry loop that asks the consent manager for the same
data repeatedly. Where it is stored is `hiu/models.py`; that it is never stored
in plaintext is enforced there and tested.

UNVERIFIED AGAINST THE SANDBOX
------------------------------
Independent reference vectors complement self-consistency tests. Neither is a
claim of a completed live sandbox transfer or milestone certification.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.integrations.abdm import curve25519

#: ABDM's key-material block names these verbatim. Sent as-is so a reviewer can
#: diff our payload against the spec without translating our vocabulary first.
CRYPTO_ALG = "ECDH"
CURVE = "Curve25519"

_NONCE_BYTES = 32
_SALT_BYTES = 20
_IV_BYTES = 12
_AES_KEY_BYTES = 32


class HiCryptoError(Exception):
    """Key material was malformed, or a payload failed to authenticate."""


@dataclass(frozen=True)
class KeyMaterial:
    """One party's half of the exchange.

    `private_key` is deliberately part of this object and deliberately never
    serialised — see `to_wire()`, which omits it. Holding it in the dataclass
    keeps the lifetime obvious at the call site instead of hiding it in module
    state where a second request could reach it.
    """

    private_key: curve25519.PrivateKey = field(repr=False)
    public_key_b64: str
    nonce_b64: str

    def to_wire(self) -> dict:
        """The half that is safe to send. The private key is not in here."""
        return {
            "cryptoAlg": CRYPTO_ALG,
            "curve": CURVE,
            "dhPublicKey": {"parameters": f"{CURVE}/32byte random key", "keyValue": self.public_key_b64},
            "nonce": self.nonce_b64,
        }


def generate_key_material() -> KeyMaterial:
    """A fresh ephemeral keypair and nonce. Never reuse one across transfers."""
    try:
        private_key, public_bytes = curve25519.generate()
    except curve25519.CurveError as exc:
        raise HiCryptoError(str(exc)) from exc
    return KeyMaterial(
        private_key=private_key,
        public_key_b64=base64.b64encode(public_bytes).decode(),
        nonce_b64=base64.b64encode(os.urandom(_NONCE_BYTES)).decode(),
    )


def _decode(value: str, *, field: str, expect: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001 — any decode failure is the same fault
        raise HiCryptoError(f"{field} is not valid base64") from exc
    if expect is not None and len(raw) != expect:
        raise HiCryptoError(f"{field} must be {expect} bytes, got {len(raw)}")
    return raw


def _xor_nonces(ours_b64: str, theirs_b64: str) -> bytes:
    ours = _decode(ours_b64, field="our nonce", expect=_NONCE_BYTES)
    theirs = _decode(theirs_b64, field="peer nonce", expect=_NONCE_BYTES)
    return bytes(a ^ b for a, b in zip(ours, theirs, strict=False))


def derive_shared_key(
    *,
    private_key: curve25519.PrivateKey,
    peer_public_key_b64: str,
    our_nonce_b64: str,
    peer_nonce_b64: str,
) -> tuple[bytes, bytes]:
    """Return (aes_key, iv).

    Both parties call this with their own private key and the other's public
    key and reach the same answer — that symmetry is what the tests pin.
    """
    peer_raw = _decode(peer_public_key_b64, field="peer public key")
    # Fidelius accepts a full point or X.509 SPKI. BC parses and validates
    # both, including the curve parameters. Never strip DER headers by length.
    if not (len(peer_raw) == 65 and peer_raw[0] == 4) and not (
        65 < len(peer_raw) <= 512 and peer_raw[0] == 0x30
    ):
        raise HiCryptoError("peer public key must be a Curve25519 point or X.509 key")

    try:
        shared = private_key.exchange(peer_raw)
    except HiCryptoError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HiCryptoError("ECDH exchange failed — key material does not match the curve") from exc

    xored = _xor_nonces(our_nonce_b64, peer_nonce_b64)
    salt, iv = xored[:_SALT_BYTES], xored[-_IV_BYTES:]

    aes_key = HKDF(
        algorithm=hashes.SHA256(),
        length=_AES_KEY_BYTES,
        salt=salt,
        info=None,
    ).derive(shared)
    return aes_key, iv


def encrypt(plaintext: str, *, aes_key: bytes, iv: bytes) -> str:
    """AES-256-GCM. Returns base64 of ciphertext||tag."""
    return base64.b64encode(AESGCM(aes_key).encrypt(iv, plaintext.encode(), None)).decode()


def decrypt(ciphertext_b64: str, *, aes_key: bytes, iv: bytes) -> str:
    """Inverse of `encrypt`.

    A tag mismatch raises rather than returning anything. Callers must not
    catch this and substitute an empty bundle: a health record that failed to
    authenticate is not an absent health record, and treating them the same is
    how tampered data becomes "the patient has no history".
    """
    raw = _decode(ciphertext_b64, field="ciphertext")
    try:
        return AESGCM(aes_key).decrypt(iv, raw, None).decode()
    except Exception as exc:  # noqa: BLE001
        raise HiCryptoError("payload failed authentication — wrong key or tampered ciphertext") from exc
