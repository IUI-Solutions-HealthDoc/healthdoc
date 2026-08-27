"""Encrypt Aadhaar numbers and OTPs for transmission to ABDM (M1).

WHY THIS EXISTS

ABDM v3 will not accept a bare Aadhaar number or a bare OTP. Both must be
RSA-encrypted with the gateway's published public certificate before they go
into a request body. That is not our policy choice — the gateway rejects the
call otherwise — but it happens to be the right one: it means the value is
unreadable to anything between us and ABDM, including our own egress proxy and
any log that captures a request body by accident.

WHAT THIS MODULE REFUSES TO DO

Persist anything. There is no cache of encrypted Aadhaar numbers, no "recently
enrolled" map, no debug hook that returns the plaintext. The plaintext exists
as a function argument and nowhere else, which is the only storage duration
that cannot leak.

It also never logs the value, the ciphertext, or their lengths. A length is not
nothing: Aadhaar is always twelve digits, so a length in a log confirms which
field was being handled.

THE PADDING IS NOT A DETAIL

ABDM specifies RSA with PKCS#1 v1.5 padding for this exchange. OAEP is the
better scheme and is what you would reach for unprompted — and it produces
ciphertext the gateway rejects. This is recorded here because the next person
to read this file will recognise PKCS1v15 as the weaker option and be tempted
to "fix" it; the interop constraint is the reason, and changing it breaks
enrolment with an error that does not mention padding.

KEY ROTATION

The certificate is ABDM's and they rotate it. It is configuration, not a
constant, so a rotation is an env change and a restart rather than a release.
`abdm_public_key_pem` holds it; when unset, every function here raises rather
than falling back to sending plaintext.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import load_pem_x509_certificate

from app.common.config import get_settings


class AbdmPublicKeyMissing(Exception):
    """No ABDM certificate configured.

    Raised rather than degrading, because every degradation available here
    means transmitting an Aadhaar number in the clear.
    """


def _load_public_key() -> rsa.RSAPublicKey:
    """Read ABDM's public key from settings.

    Accepts either a bare PUBLIC KEY block or a full CERTIFICATE, because ABDM
    has published both shapes at different times and an operator pasting what
    the portal gave them should not have to know which one this wants.
    """
    settings = get_settings()
    pem = (settings.abdm_public_key_pem or "").strip()
    if not pem or pem == "change-me":
        raise AbdmPublicKeyMissing(
            "ABDM_PUBLIC_KEY_PEM is unset. Fetch the current certificate from the "
            "ABDM portal; without it an Aadhaar number cannot be encrypted, and "
            "sending one unencrypted is not an option this code will take."
        )

    # Env vars carry \n literally more often than not.
    pem = pem.replace("\\n", "\n").encode()

    if b"BEGIN CERTIFICATE" in pem:
        key = load_pem_x509_certificate(pem).public_key()
    else:
        key = serialization.load_pem_public_key(pem)

    if not isinstance(key, rsa.RSAPublicKey):
        raise AbdmPublicKeyMissing(
            f"ABDM_PUBLIC_KEY_PEM is a {type(key).__name__}, not an RSA public key"
        )
    return key


def encrypt_for_abdm(value: str) -> str:
    """RSA-encrypt `value` and return it base64-encoded, as the gateway expects.

    Used for the Aadhaar number, the mobile number and the OTP. One function
    rather than three so there is a single place where the padding is chosen —
    three copies would eventually disagree, and the failure mode of disagreeing
    is a gateway rejection that names none of the three.
    """
    if not value:
        raise ValueError("refusing to encrypt an empty value")

    ciphertext = _load_public_key().encrypt(
        value.encode(),
        # See the module docstring: ABDM specifies PKCS#1 v1.5 here. OAEP is
        # stronger and is rejected by the gateway.
        padding.PKCS1v15(),
    )
    return base64.b64encode(ciphertext).decode()


def is_configured() -> bool:
    """True when an Aadhaar flow could actually run.

    Lets a router register an endpoint and answer 503 with a clear reason,
    rather than deciding at import time whether ABDM exists — the same shape
    AbdmClient.is_configured uses.
    """
    try:
        _load_public_key()
    except Exception:
        return False
    return True
