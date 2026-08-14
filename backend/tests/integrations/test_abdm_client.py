"""Tests for the ABDM gateway client.

Every test runs against an httpx.MockTransport — no network, no credentials,
no sandbox. That is deliberate: this client is the dependency for M1 and M3,
so it has to be verifiable before the sandbox credentials exist, not after.

What these prove, in the order the failures would actually bite:
  - placeholder credentials fail loudly instead of producing a confusing 401
  - the session token is fetched once and reused
  - concurrent callers on a cold cache produce ONE session call, not N
  - a 401 triggers exactly one refresh-and-retry, and a second 401 raises
  - transport failures and 5xx become AbdmUnavailable (degrade, don't fail)
  - 4xx becomes AbdmRejected carrying the gateway's explanation
  - every authenticated call carries Authorization, REQUEST-ID, TIMESTAMP, X-CM-ID
  - the REQUEST-ID we sent comes back to the caller for the audit row
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.integrations.abdm.client import (
    AbdmAuthError,
    AbdmClient,
    AbdmNotConfigured,
    AbdmRejected,
    AbdmUnavailable,
)

pytestmark = pytest.mark.asyncio

CREDS = {"client_id": "test-client", "client_secret": "test-secret"}


def _client(handler, **kw) -> AbdmClient:
    return AbdmClient(
        base_url="https://gateway.test",
        transport=httpx.MockTransport(handler),
        **{**CREDS, **kw},
    )


def _session_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"accessToken": "tok-1", "expiresIn": 1800})


# --------------------------------------------------------------- configuration
async def test_placeholder_credentials_raise_before_any_request():
    """'change-me' must fail as a config error, not as a gateway 401.

    Otherwise the first person to run this on a fresh checkout spends an hour
    debugging ABDM instead of reading their .env.
    """
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    client = AbdmClient(
        base_url="https://gateway.test",
        client_id="change-me",
        client_secret="change-me",
        transport=httpx.MockTransport(handler),
    )
    assert client.is_configured is False
    with pytest.raises(AbdmNotConfigured):
        await client.request("GET", "/v3/anything")
    assert calls == [], "must not reach the network with placeholder credentials"


# ----------------------------------------------------------------------- token
async def test_token_is_fetched_once_and_reused():
    sessions = 0

    def handler(request):
        nonlocal sessions
        if request.url.path == "/v3/sessions":
            sessions += 1
            return _session_ok(request)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    await client.request("GET", "/v3/a")
    await client.request("GET", "/v3/b")
    await client.request("GET", "/v3/c")
    assert sessions == 1, "token should be cached across calls"


async def test_concurrent_cold_start_makes_one_session_call():
    """The thundering-herd case the lock exists for.

    Without it, ten requests arriving on an empty cache produce ten session
    calls — which ABDM rate-limits, so the failure is intermittent and looks
    like the gateway being flaky.
    """
    sessions = 0

    async def handler(request):
        nonlocal sessions
        if request.url.path == "/v3/sessions":
            sessions += 1
            await asyncio.sleep(0.05)  # make the race wide enough to lose
            return _session_ok(request)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    await asyncio.gather(*(client.request("GET", f"/v3/{i}") for i in range(10)))
    assert sessions == 1, f"expected one session fetch, got {sessions}"


async def test_expired_token_is_refetched():
    sessions = 0

    def handler(request):
        nonlocal sessions
        if request.url.path == "/v3/sessions":
            sessions += 1
            # expiresIn below the safety margin => already stale on arrival
            return httpx.Response(200, json={"accessToken": f"tok-{sessions}", "expiresIn": 1})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    await client.request("GET", "/v3/a")
    await client.request("GET", "/v3/b")
    assert sessions == 2


async def test_session_without_access_token_is_unavailable_not_crash():
    def handler(request):
        if request.url.path == "/v3/sessions":
            return httpx.Response(200, json={"unexpected": "shape"})
        return httpx.Response(200, json={})

    with pytest.raises(AbdmUnavailable):
        await _client(handler).request("GET", "/v3/a")


async def test_bad_credentials_raise_auth_error_not_unavailable():
    """A wrong secret must not look like an outage.

    identity/router.py degrades gracefully on AbdmUnavailable and stores the
    record unverified. If bad credentials arrived as Unavailable, every patient
    would be silently marked unverified and nobody would notice for weeks.
    """
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(AbdmAuthError):
        await _client(handler).request("GET", "/v3/a")


# -------------------------------------------------------------------- retrying
async def test_401_on_call_refreshes_once_then_succeeds():
    sessions = 0
    call_attempts = 0

    def handler(request):
        nonlocal sessions, call_attempts
        if request.url.path == "/v3/sessions":
            sessions += 1
            return httpx.Response(200, json={"accessToken": f"tok-{sessions}", "expiresIn": 1800})
        call_attempts += 1
        if call_attempts == 1:
            return httpx.Response(401, json={"error": "token revoked"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    resp = await client.request("GET", "/v3/a")
    assert resp.body == {"ok": True}
    assert sessions == 2, "should have forced one refresh"
    assert call_attempts == 2, "exactly one retry"


async def test_second_401_raises_rather_than_looping():
    sessions = 0
    attempts = 0

    def handler(request):
        nonlocal sessions, attempts
        if request.url.path == "/v3/sessions":
            sessions += 1
            return httpx.Response(200, json={"accessToken": "tok", "expiresIn": 1800})
        attempts += 1
        return httpx.Response(401, json={"error": "nope"})

    client = _client(handler)
    with pytest.raises(AbdmAuthError):
        await client.request("GET", "/v3/a")
    assert attempts == 2, "must not retry more than once"


# ---------------------------------------------------------------- error mapping
async def test_transport_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(AbdmUnavailable):
        await _client(handler).request("GET", "/v3/a")


async def test_5xx_is_unavailable():
    def handler(request):
        if request.url.path == "/v3/sessions":
            return _session_ok(request)
        return httpx.Response(503, text="upstream down")

    with pytest.raises(AbdmUnavailable):
        await _client(handler).request("GET", "/v3/a")


async def test_4xx_is_rejected_and_carries_the_gateway_explanation():
    def handler(request):
        if request.url.path == "/v3/sessions":
            return _session_ok(request)
        return httpx.Response(400, json={"code": "ABDM-1042", "message": "invalid abha address"})

    with pytest.raises(AbdmRejected) as exc:
        await _client(handler).request("POST", "/v3/enrol", json={"x": 1})
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "ABDM-1042"
    assert exc.value.request_id


# -------------------------------------------------------------------- headers
async def test_authenticated_calls_carry_every_required_header():
    seen = {}

    def handler(request):
        if request.url.path == "/v3/sessions":
            return _session_ok(request)
        seen.update(request.headers)
        return httpx.Response(200, json={})

    await _client(handler).request("POST", "/v3/a", json={"k": "v"})
    assert seen["authorization"] == "Bearer tok-1"
    assert seen["x-cm-id"] == "sbx"
    assert seen["request-id"]
    # ABDM wants ISO-8601 UTC to milliseconds with a Z.
    assert seen["timestamp"].endswith("Z")
    assert "T" in seen["timestamp"]
    assert seen["content-type"] == "application/json"


async def test_request_id_is_returned_for_the_audit_row():
    """fhir_bundle_transactions.abdm_request_id (0026) is how a transmission is
    traced in ABDM's own logs during certification."""
    sent = {}

    def handler(request):
        if request.url.path == "/v3/sessions":
            return _session_ok(request)
        sent["rid"] = request.headers["REQUEST-ID"]
        return httpx.Response(200, json={})

    resp = await _client(handler).request("GET", "/v3/a")
    assert resp.request_id == sent["rid"]


async def test_caller_supplied_request_id_is_used_for_idempotent_retry():
    """ABDM treats REQUEST-ID as the idempotency key on several endpoints, so a
    genuine retry has to carry the original id rather than mint a new one."""
    seen = []

    def handler(request):
        if request.url.path == "/v3/sessions":
            return _session_ok(request)
        seen.append(request.headers["REQUEST-ID"])
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.request("POST", "/v3/a", json={}, request_id="fixed-id")
    await client.request("POST", "/v3/a", json={}, request_id="fixed-id")
    assert seen == ["fixed-id", "fixed-id"]
