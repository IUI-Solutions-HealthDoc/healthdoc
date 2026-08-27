"""Token verification — the one function that decides who anybody is.

WHY THIS FILE EXISTS

Every other test in this suite authenticates by overriding get_current_user:

    app.dependency_overrides[get_current_user] = lambda: auth_user

That is the right call for a router test — it isolates the thing under test.
The consequence is that `get_current_user` itself, which verifies the signature
on every request the system ever serves, had NO test at all. The migration off
python-jose changed the library performing that verification, and the suite
would have stayed green if the new code accepted unsigned tokens.

So these tests mint real RS256 tokens against a real JWKS and assert on
rejections rather than acceptance. The happy path is one test; the other nine
are the ways a token must fail.

No secrets here: the RSA key is generated per-run and lives only in memory.
"""
from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import deps

ISSUER = "https://idp.test/realms/healthdoc"
KID = "test-key-1"
OTHER_KID = "test-key-2"


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwk_from_public(public_key, kid: str) -> dict:
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
        "n": _b64url_uint(numbers.n), "e": _b64url_uint(numbers.e),
    }


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@pytest.fixture(scope="module")
def other_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@pytest.fixture
def jwks(keypair, other_keypair):
    return {"keys": [
        _jwk_from_public(keypair[1], KID),
        _jwk_from_public(other_keypair[1], OTHER_KID),
    ]}


@pytest.fixture(autouse=True)
def _wire(monkeypatch, jwks):
    """Point deps at our JWKS and issuer; leave audience off unless a test sets it."""
    async def _fake_jwks():
        return jwks

    monkeypatch.setattr(deps, "_get_jwks", _fake_jwks)

    class _S:
        jwt_issuer = ISSUER
        jwt_audience = None

    monkeypatch.setattr(deps, "get_settings", lambda: _S())
    return _S


def _mint(private_key, *, kid=KID, iss=ISSUER, aud=None, sub="user-sub-1",
          exp_delta=3600, omit=()):
    now = int(time.time())
    claims = {
        "sub": sub, "iss": iss, "iat": now, "exp": now + exp_delta,
        "preferred_username": "dev.doctor",
        "realm_access": {"roles": ["doctor"]},
        "amr": ["pwd"],
    }
    if aud is not None:
        claims["aud"] = aud
    for field in omit:
        claims.pop(field, None)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


class _Creds:
    def __init__(self, token: str) -> None:
        self.credentials = token


async def _call(token: str):
    return await deps.get_current_user(_Creds(token))


# --------------------------------------------------------------- happy path

@pytest.mark.asyncio
async def test_a_properly_signed_token_is_accepted(keypair):
    user = await _call(_mint(keypair[0]))
    assert user.sub == "user-sub-1"
    assert user.roles == ["doctor"]
    assert user.amr == ["pwd"]


# ------------------------------------------------------------- the refusals

@pytest.mark.asyncio
async def test_a_token_signed_by_another_key_is_refused(keypair, other_keypair):
    """Signed by key 2 but claiming kid 1 — the substitution attack."""
    from fastapi import HTTPException

    token = _mint(other_keypair[0], kid=KID)
    with pytest.raises(HTTPException) as caught:
        await _call(token)
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_an_unknown_kid_is_refused_not_guessed(keypair):
    """python-jose was handed the whole JWKS and chose internally. Selecting by
    kid explicitly means an unpublished key is refused rather than matched
    against whatever else happens to be in the set."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], kid="not-a-published-kid"))
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(keypair):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], exp_delta=-60))
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_a_token_with_no_exp_never_expires_so_it_is_refused(keypair):
    """PyJWT does not require exp by default. Without options["require"] a
    token minted with no expiry would be valid forever."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], omit=("exp",)))
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_a_token_with_no_sub_is_refused(keypair):
    """`sub` is what every facility scope and audit row hangs off."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], omit=("sub",)))
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_a_foreign_issuer_is_refused(keypair):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], iss="https://evil.test/realms/healthdoc"))
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_the_401_body_does_not_say_WHY(keypair):
    """The old message was f"Invalid token: {exc}".

    Telling a caller whether the signature, the expiry or the issuer failed is
    a free oracle: an attacker probing with forged tokens learns exactly which
    check to work on next. The reason belongs in the log.
    """
    from fastapi import HTTPException

    for token in (
        _mint(keypair[0], exp_delta=-60),
        _mint(keypair[0], iss="https://evil.test/realms/healthdoc"),
        _mint(keypair[0], kid="not-a-published-kid"),
    ):
        with pytest.raises(HTTPException) as caught:
            await _call(token)
        assert caught.value.detail == "Invalid token", (
            f"401 body leaked a reason: {caught.value.detail!r}"
        )


# ----------------------------------------------------------------- audience

@pytest.mark.asyncio
async def test_audience_is_enforced_when_configured(monkeypatch, keypair):
    class _S:
        jwt_issuer = ISSUER
        jwt_audience = "healthdoc-backend"

    monkeypatch.setattr(deps, "get_settings", lambda: _S())

    ok = await _call(_mint(keypair[0], aud="healthdoc-backend"))
    assert ok.sub == "user-sub-1"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0], aud="some-other-client"))
    assert caught.value.status_code == 401, (
        "a token minted for a different client in the same realm was accepted"
    )


@pytest.mark.asyncio
async def test_audience_is_not_checked_when_unset(keypair):
    """Documents the permissive default rather than hiding it.

    This is the behaviour python-jose had behind `verify_aud: False`. It stays
    for dev because enabling it against a realm with no audience mapper locks
    everyone out — and app/main.py refuses to BOOT in production while
    JWT_AUDIENCE is unset, which is what stops it reaching anywhere real.
    """
    user = await _call(_mint(keypair[0], aud="anything-at-all"))
    assert user.sub == "user-sub-1"


# ------------------------------------------------------------ IdP outage

@pytest.mark.asyncio
async def test_jwks_outage_is_503_not_401(monkeypatch, keypair):
    """A 401 would tell every user their credentials are wrong during our own
    outage, and would send support chasing password resets."""
    import httpx
    from fastapi import HTTPException

    async def _boom():
        raise httpx.ConnectError("jwks unreachable")

    monkeypatch.setattr(deps, "_get_jwks", _boom)

    with pytest.raises(HTTPException) as caught:
        await _call(_mint(keypair[0]))
    assert caught.value.status_code == 503
