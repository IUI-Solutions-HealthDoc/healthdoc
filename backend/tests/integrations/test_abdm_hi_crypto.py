"""ECDH/AES-GCM health-information transfer crypto (M2/M3 key handling).

These pin the properties an assessor asks about, not the implementation:
both parties reach the same key, a wrong key does not silently produce
plausible plaintext, tampering is detected, and a private key never appears in
anything we send.

What they deliberately do NOT claim: that ABDM agrees. Every test here is
self-consistency between our two halves. Only a sandbox round trip proves
interoperability, and pretending otherwise is how an unverified integration
gets described as tested.
"""
from __future__ import annotations

import base64
import json

import pytest

from app.integrations.abdm import hi_crypto


def _pair():
    return hi_crypto.generate_key_material(), hi_crypto.generate_key_material()


def _keys_for(a, b):
    return hi_crypto.derive_shared_key(
        private_key=a.private_key,
        peer_public_key_b64=b.public_key_b64,
        our_nonce_b64=a.nonce_b64,
        peer_nonce_b64=b.nonce_b64,
    )


def test_both_parties_derive_the_same_key_and_iv():
    """The whole exchange rests on this. If it ever fails, nothing else matters."""
    hip, hiu = _pair()
    assert _keys_for(hip, hiu) == _keys_for(hiu, hip)


def test_a_bundle_encrypted_by_one_side_opens_on_the_other():
    hip, hiu = _pair()
    key, iv = _keys_for(hip, hiu)
    bundle = json.dumps({"resourceType": "Bundle", "entry": []})

    ciphertext = hi_crypto.encrypt(bundle, aes_key=key, iv=iv)
    peer_key, peer_iv = _keys_for(hiu, hip)

    assert hi_crypto.decrypt(ciphertext, aes_key=peer_key, iv=peer_iv) == bundle


def test_the_private_key_is_not_in_what_we_send():
    """to_wire() is the only thing that leaves the process. If a private key
    ever reaches it, every transfer this key material protects is readable by
    whoever holds the gateway logs."""
    material = hi_crypto.generate_key_material()
    wire = json.dumps(material.to_wire())

    private_raw = material.private_key.private_bytes_raw()
    assert base64.b64encode(private_raw).decode() not in wire
    assert private_raw.hex() not in wire
    # Structural, not a keyword scan: the exact field set, so a future field
    # cannot be added without this failing and being looked at.
    assert set(material.to_wire()) == {"cryptoAlg", "curve", "dhPublicKey", "nonce"}
    assert set(material.to_wire()["dhPublicKey"]) == {"parameters", "keyValue"}


def test_a_third_party_key_does_not_open_the_payload():
    """An eavesdropper with their own keypair and both nonces gets nothing."""
    hip, hiu = _pair()
    key, iv = _keys_for(hip, hiu)
    ciphertext = hi_crypto.encrypt("sensitive", aes_key=key, iv=iv)

    attacker = hi_crypto.generate_key_material()
    wrong_key, wrong_iv = hi_crypto.derive_shared_key(
        private_key=attacker.private_key,
        peer_public_key_b64=hip.public_key_b64,
        our_nonce_b64=hiu.nonce_b64,
        peer_nonce_b64=hip.nonce_b64,
    )
    with pytest.raises(hi_crypto.HiCryptoError):
        hi_crypto.decrypt(ciphertext, aes_key=wrong_key, iv=wrong_iv)


def test_tampering_is_detected_rather_than_decrypted():
    """GCM's whole job. A flipped bit must not yield 'the patient has no history'."""
    hip, hiu = _pair()
    key, iv = _keys_for(hip, hiu)
    ciphertext = hi_crypto.encrypt('{"resourceType":"Bundle"}', aes_key=key, iv=iv)

    raw = bytearray(base64.b64decode(ciphertext))
    raw[0] ^= 0x01
    tampered = base64.b64encode(bytes(raw)).decode()

    with pytest.raises(hi_crypto.HiCryptoError):
        hi_crypto.decrypt(tampered, aes_key=key, iv=iv)


def test_the_iv_depends_on_both_nonces():
    """Neither side alone fixes the IV. If one could, a party that reuses a
    nonce would silently repeat an IV under the same key — the one thing
    GCM must never do."""
    hip, hiu = _pair()
    _, iv_original = _keys_for(hip, hiu)

    other_peer = hi_crypto.generate_key_material()
    _, iv_other = hi_crypto.derive_shared_key(
        private_key=hip.private_key,
        peer_public_key_b64=hiu.public_key_b64,
        our_nonce_b64=hip.nonce_b64,
        peer_nonce_b64=other_peer.nonce_b64,
    )
    assert iv_original != iv_other


@pytest.mark.parametrize(
    "kwargs",
    [
        {"peer_public_key_b64": "not base64!!"},
        {"peer_public_key_b64": base64.b64encode(b"too short").decode()},
        {"peer_nonce_b64": base64.b64encode(b"short nonce").decode()},
    ],
    ids=["unparseable-key", "wrong-length-key", "wrong-length-nonce"],
)
def test_malformed_key_material_raises_our_error_not_a_stray_exception(kwargs):
    """Callers catch HiCryptoError. A ValueError escaping from a base64 decode
    would surface as a 500 on a consent-bearing endpoint."""
    hip, hiu = _pair()
    call = {
        "private_key": hip.private_key,
        "peer_public_key_b64": hiu.public_key_b64,
        "our_nonce_b64": hip.nonce_b64,
        "peer_nonce_b64": hiu.nonce_b64,
        **kwargs,
    }
    with pytest.raises(hi_crypto.HiCryptoError):
        hi_crypto.derive_shared_key(**call)


def test_an_uncompressed_point_prefix_is_accepted():
    """Implementations differ on whether the 0x04 prefix is sent. Accepting
    both is interoperability; accepting any length would be guessing."""
    hip, hiu = _pair()
    prefixed = base64.b64encode(b"\x04" + base64.b64decode(hiu.public_key_b64)).decode()

    plain_key, _ = _keys_for(hip, hiu)
    prefixed_key, _ = hi_crypto.derive_shared_key(
        private_key=hip.private_key,
        peer_public_key_b64=prefixed,
        our_nonce_b64=hip.nonce_b64,
        peer_nonce_b64=hiu.nonce_b64,
    )
    assert plain_key == prefixed_key


def test_every_generated_keypair_is_fresh():
    """Reuse across transfers would mean one compromised key opens many."""
    materials = [hi_crypto.generate_key_material() for _ in range(10)]
    assert len({m.public_key_b64 for m in materials}) == 10
    assert len({m.nonce_b64 for m in materials}) == 10
