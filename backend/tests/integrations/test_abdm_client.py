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
import json

import httpx
import pytest

from app.integrations.abdm.client import (
    AbdmAuthError,
    AbdmClient,
    AbdmError,
    AbdmNotConfigured,
    AbdmRejected,
    AbdmUnavailable,
)

pytestmark = pytest.mark.asyncio

CREDS = {"client_id": "test-client", "client_secret": "test-secret"}
SESSION_PATH = "/api/hiecm/gateway/v3/sessions"


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
async def test_session_uses_the_official_v3_contract():
    """Keep origin/path joining aligned with ABDM's current gateway OpenAPI."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        seen["headers"] = request.headers
        return httpx.Response(202, json={"accessToken": "tok-1", "expiresIn": 1200})

    client = AbdmClient(
        base_url="https://dev.abdm.gov.in",
        transport=httpx.MockTransport(handler),
        **CREDS,
    )
    token = await client._token()

    assert token == "tok-1"
    assert seen["url"] == "https://dev.abdm.gov.in/api/hiecm/gateway/v3/sessions"
    assert seen["body"] == {
        "clientId": "test-client",
        "clientSecret": "test-secret",
        "grantType": "client_credentials",
    }
    assert seen["headers"]["X-CM-ID"] == "sbx"
    assert seen["headers"]["REQUEST-ID"]
    assert seen["headers"]["TIMESTAMP"].endswith("Z")


async def test_token_is_fetched_once_and_reused():
    sessions = 0

    def handler(request):
        nonlocal sessions
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
            return _session_ok(request)
        return httpx.Response(503, text="upstream down")

    with pytest.raises(AbdmUnavailable):
        await _client(handler).request("GET", "/v3/a")


async def test_4xx_is_rejected_and_carries_the_gateway_explanation():
    def handler(request):
        if request.url.path == SESSION_PATH:
            return _session_ok(request)
        return httpx.Response(400, json={"code": "ABDM-1042", "message": "invalid abha address"})

    with pytest.raises(AbdmRejected) as exc:
        await _client(handler).request("POST", "/v3/enrol", json={"x": 1})
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "ABDM-1042"
    assert exc.value.request_id


async def test_failure_diagnostics_do_not_include_credentials_or_patient_content():
    from app.integrations.abdm.client import safe_failure_summary

    body = {"error": {"code": "ABDM-1042: ", "message": "SECRET-TOKEN patient@sbx"}}
    exc = AbdmRejected(400, body, "SECRET-REQUEST-ID")
    assert exc.detail == body
    assert safe_failure_summary(exc) == "AbdmRejected:request:400:ABDM-1042"
    for rendered in (str(exc), repr(exc), safe_failure_summary(exc)):
        assert "SECRET" not in rendered and "patient@sbx" not in rendered
    exc.detail = [{"code": "SECRET-TOKEN"}, {"code": "ABDM-1042 patient@sbx"}]
    assert safe_failure_summary(exc) == "AbdmRejected:request:400"


@pytest.mark.parametrize(("stage", "status"), [("session", 500), ("request", 403)])
async def test_failure_diagnostics_distinguish_session_from_operation(stage, status):
    from app.integrations.abdm.client import safe_failure_summary

    def handler(request):
        if stage == "session" or request.url.path != SESSION_PATH:
            return httpx.Response(status, json={"message": "SECRET-TOKEN patient@sbx"})
        return _session_ok(request)

    error_type = AbdmUnavailable if status == 500 else AbdmAuthError
    with pytest.raises(error_type) as caught:
        await _client(handler).request("POST", "/v3/link")
    assert safe_failure_summary(caught.value) == f"{error_type.__name__}:{stage}:{status}"


@pytest.mark.parametrize("status", [401, 403, 500])
@pytest.mark.parametrize("stage", ["session", "request"])
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"error": {"code": "ABDM-1066", "message": "SECRET patient@sbx"}}, "ABDM-1066"),
        ({"fault": {"code": 900908, "description": "SECRET patient@sbx"}}, "900908"),
        ({"code": "900910", "message": "SECRET patient@sbx"}, "900910"),
        ({"code": "12345678901234", "message": "SECRET patient@sbx"}, ""),
        ({"fault": {"code": "900908 SECRET patient@sbx"}}, ""),
    ],
)
async def test_auth_and_outage_errors_keep_only_safe_codes(status, stage, body, expected):
    from app.integrations.abdm.client import safe_failure_summary

    def handler(request):
        if stage == "session" or request.url.path != SESSION_PATH:
            return httpx.Response(status, json=body)
        return _session_ok(request)

    error_type = AbdmUnavailable if status == 500 else AbdmAuthError
    with pytest.raises(error_type) as caught:
        await _client(handler).request("POST", "/v3/link")
    summary = safe_failure_summary(caught.value)
    suffix = f":{expected}" if expected else ""
    assert summary == f"{error_type.__name__}:{stage}:{status}{suffix}"
    assert not hasattr(caught.value, "detail"), "Auth error must not retain its raw body"
    for rendered in (summary, str(caught.value), repr(caught.value)):
        assert "SECRET" not in rendered and "patient@sbx" not in rendered


@pytest.mark.parametrize("stage", ["session", "request"])
async def test_transport_failure_retains_stage_without_transport_details(stage):
    from app.integrations.abdm.client import safe_failure_summary

    def handler(request):
        if stage == "session" or request.url.path != SESSION_PATH:
            raise httpx.ConnectError("SECRET patient@sbx", request=request)
        return _session_ok(request)

    with pytest.raises(AbdmUnavailable) as caught:
        await _client(handler).request("POST", "/v3/link")
    assert safe_failure_summary(caught.value) == f"AbdmUnavailable:{stage}"


@pytest.mark.parametrize("status", [301, 302, 303, 304, 307, 308])
@pytest.mark.parametrize("stage", ["session", "request"])
async def test_redirect_is_not_success_and_never_forwards_secrets(status, stage, caplog):
    from app.integrations.abdm.client import safe_failure_summary

    seen = []

    def handler(request):
        seen.append(request)
        if stage == "request" and request.url.path == SESSION_PATH:
            return _session_ok(request)
        # Even a redirect carrying a plausible token is not a session response.
        return httpx.Response(
            status,
            headers={"Location": "https://other.test/SECRET?patient=patient@sbx"},
            json={"accessToken": "SECRET", "expiresIn": 1800},
        )

    client = _client(handler)
    try:
        with pytest.raises(AbdmError) as caught:
            await client.request("POST", "/v3/link", json={"patient": "patient@sbx"})
        assert type(caught.value).__name__ == "AbdmProtocolError"
        assert safe_failure_summary(caught.value) == f"AbdmProtocolError:{stage}:{status}"
        assert len(seen) == (1 if stage == "session" else 2)
        assert all(request.url.host == "gateway.test" for request in seen)
        assert not hasattr(caught.value, "detail")
        for rendered in (str(caught.value), repr(caught.value), caplog.text):
            assert "SECRET" not in rendered and "patient@sbx" not in rendered
        if stage == "session":
            assert client._tokens.get_if_fresh() is None
    finally:
        await client.aclose()


# -------------------------------------------------------------------- headers
async def test_authenticated_calls_carry_every_required_header():
    seen = {}

    def handler(request):
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
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
        if request.url.path == SESSION_PATH:
            return _session_ok(request)
        seen.append(request.headers["REQUEST-ID"])
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.request("POST", "/v3/a", json={}, request_id="fixed-id")
    await client.request("POST", "/v3/a", json={}, request_id="fixed-id")
    assert seen == ["fixed-id", "fixed-id"]
