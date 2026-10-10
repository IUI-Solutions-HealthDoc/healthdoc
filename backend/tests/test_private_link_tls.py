"""The control-room server's links to the hospital server verify, not just encrypt.

ssl.create_default_context() checks the chain and the host name: libpq's
verify-full. These pin that the configured CA reaches both the database engine
and the signing-key fetch, and that nothing changes when it is unset (one host,
one Docker network). The real handshake is exercised against PostgreSQL and
Keycloak in docs/control-room-design-2026-10-10.md, "Encryption".
"""

import ssl

import certifi
import pytest

from app.auth import deps
from app.common import db


def test_no_ca_means_a_plain_connection():
    assert db._connect_args(None) == {}


def test_a_ca_means_verified_tls_to_the_database():
    context = db._connect_args(certifi.where())["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


@pytest.mark.asyncio
@pytest.mark.parametrize("ca_file", [None, "ca"])
async def test_the_signing_key_fetch_trusts_only_the_configured_ca(monkeypatch, ca_file):
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"keys": []}
            return Response()

    settings = deps.get_settings()
    monkeypatch.setattr(settings, "jwt_jwks_url", "https://10.0.0.5:8443/certs")
    monkeypatch.setattr(settings, "jwt_jwks_ca_file", certifi.where() if ca_file else None)
    monkeypatch.setattr(deps.httpx, "AsyncClient", Client)
    monkeypatch.setitem(deps._jwks_cache, "keys", None)
    await deps._get_jwks()
    if ca_file:
        assert isinstance(seen["verify"], ssl.SSLContext) and seen["verify"].check_hostname
    else:
        assert seen["verify"] is True
