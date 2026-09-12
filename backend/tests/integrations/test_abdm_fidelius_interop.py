"""Public known-answer vector, not HealthDoc encrypting to itself.

Source: mgrmtech/fidelius-cli README at 4d9b4a5f65d61607dafcea3e28e3d257e425fcd9.
All keys below are PUBLISHED TEST material, never credentials or patient data.
"""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.integrations.abdm import curve25519, hi_crypto

SENDER_PRIVATE = "AYhVZpbVeX4KS5Qm/W0+9Ye2q3rnVVGmqRICmseWni4="
SENDER_PUBLIC = (
    "BABVt+mpRLMXiQpIfEq6bj8hlXsdtXIxLsspmMgLNI1SR5mHgDVbjHO2A+U4QlMddGzqyEidzm1AkhtSxSO2Ahg="
)
RECEIVER_PRIVATE = "DMxHPri8d7IT23KgLk281zZenMfVHSdeamq0RhwlIBk="
RECEIVER_PUBLIC = (
    "BAheD5rUqTy4V5xR4/6HWmYpopu5CO+KO8BECS0udNqUTSNo91TIqIIy1A4Vh+F94c+n9vAcwXU2bGcfsI5f69Y="
)
RECEIVER_X509 = "MIIBMTCB6gYHKoZIzj0CATCB3gIBATArBgcqhkjOPQEBAiB/////////////////////////////////////////7TBEBCAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqYSRShRAQge0Je0Je0Je0Je0Je0Je0Je0Je0Je0Je0JgtenHcQyGQEQQQqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq0kWiCuGaG4oIa04B7dLHdI0UySPU1+bXxhsinpxaJ+ztPZAiAQAAAAAAAAAAAAAAAAAAAAFN753qL3nNZYEmMaXPXT7QIBCANCAAQIXg+a1Kk8uFecUeP+h1pmKaKbuQjvijvARAktLnTalE0jaPdUyKiCMtQOFYfhfeHPp/bwHMF1NmxnH7COX+vW"
SENDER_NONCE = "lmXgblZwotx+DfBgKJF0lZXtAXgBEYr5khh79Zytr2Y="
RECEIVER_NONCE = "6uj1RdDUbcpI3lVMZvijkMC8Te20O4Bcyz0SyivX8Eg="
PLAINTEXT = "Wormtail should never have been Potter cottage's secret keeper."
CIPHERTEXT = "pzMvVZNNVtJzqPkkxcCbBUWgDEBy/mBXIeT2dJWI16ZAQnnXUb9lI+S4k8XK6mgZSKKSRIHkcNvJpllnBg548wUgavBa0vCRRwdL6kY6Yw=="


def derive(private, public, ours, theirs):
    return hi_crypto.derive_shared_key(
        private_key=curve25519.PrivateKey(base64.b64decode(private)),
        peer_public_key_b64=public,
        our_nonce_b64=ours,
        peer_nonce_b64=theirs,
    )


@pytest.mark.parametrize("public", [RECEIVER_PUBLIC, RECEIVER_X509], ids=["point", "x509"])
def test_healthdoc_produces_fidelius_exact_ciphertext(public):
    key, iv = derive(SENDER_PRIVATE, public, SENDER_NONCE, RECEIVER_NONCE)
    assert hi_crypto.encrypt(PLAINTEXT, aes_key=key, iv=iv) == CIPHERTEXT


def test_healthdoc_decrypts_fidelius_known_ciphertext():
    key, iv = derive(RECEIVER_PRIVATE, SENDER_PUBLIC, RECEIVER_NONCE, SENDER_NONCE)
    assert hi_crypto.decrypt(CIPHERTEXT, aes_key=key, iv=iv) == PLAINTEXT


@pytest.mark.parametrize(
    "kind", ["zero-point", "p256-point", "p256-x509", "zero-scalar", "large-scalar"]
)
def test_invalid_points_and_foreign_curves_are_not_reinterpreted(kind):
    private, public = SENDER_PRIVATE, RECEIVER_PUBLIC
    if kind == "zero-point":
        public = base64.b64encode(b"\x04" + bytes(64)).decode()
    elif kind.startswith("p256"):
        key = ec.generate_private_key(ec.SECP256R1()).public_key()
        fmt = (
            serialization.PublicFormat.SubjectPublicKeyInfo
            if kind.endswith("x509")
            else serialization.PublicFormat.UncompressedPoint
        )
        encoding = (
            serialization.Encoding.DER if kind.endswith("x509") else serialization.Encoding.X962
        )
        public = base64.b64encode(key.public_bytes(encoding, fmt)).decode()
    else:
        private = base64.b64encode(bytes(32) if kind == "zero-scalar" else b"\xff" * 32).decode()
    with pytest.raises(hi_crypto.HiCryptoError):
        derive(private, public, SENDER_NONCE, RECEIVER_NONCE)


def test_stored_keys_are_versioned_and_legacy_keys_are_not_reinterpreted():
    key = curve25519.PrivateKey(base64.b64decode(SENDER_PRIVATE))
    assert curve25519.deserialize(curve25519.serialize(key)) == key
    assert SENDER_PRIVATE not in repr(key)
    assert key.scalar.hex() not in repr(key)
    with pytest.raises(curve25519.CurveError, match="Legacy"):
        curve25519.deserialize(key.scalar.hex())
