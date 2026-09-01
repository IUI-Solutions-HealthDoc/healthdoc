"""`_verify_with_gateway` — the call that had never once succeeded.

There were no tests on this function. That is not incidental to the bug, it is
the whole explanation: the old implementation sent `abdm_client_secret` as a
Bearer token, 401'd on every call, swallowed it in `except Exception`, and
logged "proceeding offline". Nothing distinguished that from a rural facility
with no internet, and nothing asserted otherwise.

So these tests are written against the DISTINCTIONS rather than the happy path.
The happy path was never the thing at risk.

NO CREDENTIALS ANYWHERE IN HERE. The client is stubbed; nothing reaches a
network. CI must never hold ABDM credentials, and these tests must stay mocked.
"""
from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.asyncio


class _StubClient:
    """Stands in for AbdmClient. Records whether it was called at all."""

    def __init__(self, *, configured: bool = True, raises=None, body=None, status=200):
        self.is_configured = configured
        self._raises = raises
        self._body = body
        self._status = status
        self.calls: list[tuple[str, str, object]] = []

    async def request(self, method, path, *, json=None, **kwargs):
        self.calls.append((method, path, json))
        if self._raises is not None:
            raise self._raises
        from app.integrations.abdm.client import AbdmResponse

        return AbdmResponse(self._status, self._body, "test-request-id")


def _install(monkeypatch, client, *, path="/v3/some/verify"):
    from app.integrations.abdm.identity import router as mod

    monkeypatch.setattr(mod, "get_abdm_client", lambda: client)
    monkeypatch.setattr(mod, "_VERIFY_PATH", path)
    return mod


async def test_unset_path_makes_no_network_call(monkeypatch):
    """No path means no request — the guard, not the shipped state.

    `_VERIFY_PATH` is set now (confirmed against the sandbox), but the guard
    stays: it is what would catch a future path being blanked or a new
    environment shipping without one, rather than firing a request built from
    a path nobody verified.
    """
    client = _StubClient()
    mod = _install(monkeypatch, client, path=None)

    assert await mod._verify_with_gateway("91123456789012") is None
    assert client.calls == [], "a request was built despite _VERIFY_PATH being None"


async def test_unconfigured_never_puts_the_secret_on_the_wire(monkeypatch):
    """The credential half of the original defect.

    `is_configured` is False while the .env placeholders are in place. The old
    code sent the placeholder anyway, in an Authorization header.
    """
    client = _StubClient(configured=False)
    mod = _install(monkeypatch, client)

    assert await mod._verify_with_gateway("91123456789012") is None
    assert client.calls == [], "called the gateway without usable credentials"


async def test_auth_failure_logs_at_error_not_as_offline(monkeypatch, caplog):
    """The distinction the old code destroyed.

    An AbdmAuthError is OUR fault — wrong credentials — and must not be
    reported the way an unreachable gateway is. The old bare `except Exception`
    logged both as "proceeding offline", which is precisely why a permanently
    broken integration survived in the tree.

    ASSERTED ON LEVEL, NOT WORDING. The first version of this test checked
    `"offline" not in message` and failed against a message reading "DOWN, not
    offline" — it matched the very word the message uses to DENY the thing
    being tested. Log prose is not an interface; the level is. An operator
    filtering at ERROR is the actual mechanism that separates "our credentials
    are wrong" from "the gateway is down", so that separation is what gets
    asserted here and in the sibling test below.
    """
    from app.integrations.abdm.client import AbdmAuthError

    client = _StubClient(raises=AbdmAuthError("rejected"))
    mod = _install(monkeypatch, client)

    with caplog.at_level(logging.DEBUG, logger="healthdoc.abdm"):
        assert await mod._verify_with_gateway("91123456789012") is None

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "credential failure was not logged at ERROR"
    # The one piece of wording that IS load-bearing: the old code's phrasing.
    # "proceeding offline" is what made this indistinguishable from a rural
    # facility, so its exact reappearance is worth catching.
    assert "proceeding offline" not in errors[0].getMessage().lower()


async def test_unavailable_gateway_is_the_real_degradation_case(monkeypatch, caplog):
    """A genuinely unreachable gateway must still not break registration."""
    from app.integrations.abdm.client import AbdmUnavailable

    client = _StubClient(raises=AbdmUnavailable("unreachable"))
    mod = _install(monkeypatch, client)

    with caplog.at_level(logging.DEBUG, logger="healthdoc.abdm"):
        assert await mod._verify_with_gateway("91123456789012") is None

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "an offline facility was logged as an error"
    )


async def test_rejection_does_not_log_the_body(monkeypatch, caplog):
    """AbdmRejected carries a gateway body, which can carry PHI. Status only."""
    from app.integrations.abdm.client import AbdmRejected

    secret_in_body = {"name": "Test Patient", "abhaNumber": "91123456789012"}
    client = _StubClient(raises=AbdmRejected(422, secret_in_body, "rid"))
    mod = _install(monkeypatch, client)

    with caplog.at_level(logging.DEBUG, logger="healthdoc.abdm"):
        assert await mod._verify_with_gateway("91123456789012") is None

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Test Patient" not in logged
    assert "91123456789012" not in logged, "the ABHA number was written to the log"


@pytest.mark.parametrize("body", [None, "", [], 0])
async def test_2xx_with_a_non_object_body_is_not_a_verification(monkeypatch, body):
    """`gateway_result is not None` is what the caller keys on.

    A 200 carrying `null` or an empty string would otherwise be truthy enough
    to mark a patient verified on the strength of an empty answer.
    """
    client = _StubClient(body=body)
    mod = _install(monkeypatch, client)

    assert await mod._verify_with_gateway("91123456789012") is None


async def test_verified_response_is_returned(monkeypatch):
    """The happy path, for completeness — a dict body means verified."""
    client = _StubClient(body={"status": "ACTIVE"})
    mod = _install(monkeypatch, client)

    assert await mod._verify_with_gateway("91123456789012") == {"status": "ACTIVE"}
    # Absolute ABHA-host URL, capitalised key, hyphenated value. All three were
    # confirmed against the sandbox; each fails as a 400/503 if got wrong.
    from app.common.config import get_settings

    base = get_settings().abdm_abha_base_url.rstrip("/")
    assert client.calls == [
        ("POST", f"{base}/v3/some/verify", {"ABHANumber": "91-1234-5678-9012"})
    ]


async def test_the_abha_number_is_sent_hyphenated(monkeypatch):
    """ABDM rejects the stored (stripped) form with 400 "Invalid ABHA Number".

    We normalise to bare digits for storage, so every outbound call has to undo
    it. Nothing else in the suite would notice, because the stub accepts
    anything and the real 400 reads like bad user input rather than a bug here.
    """
    client = _StubClient(body={"status": "ACTIVE"})
    mod = _install(monkeypatch, client)

    await mod._verify_with_gateway("91123456789012")
    sent = client.calls[0][2]["ABHANumber"]
    assert sent == "91-1234-5678-9012"


async def test_the_body_key_is_capitalised(monkeypatch):
    """`abhaNumber` returns 400 "Invalid ABHA Number" — the key, not the value."""
    client = _StubClient(body={"status": "ACTIVE"})
    mod = _install(monkeypatch, client)

    await mod._verify_with_gateway("91123456789012")
    body = client.calls[0][2]
    assert "ABHANumber" in body
    assert "abhaNumber" not in body


@pytest.mark.parametrize(
    "stored", ["", "91", "9112345678901", "911234567890123", "91-abcd-5678-9012"]
)
async def test_a_number_that_cannot_be_hyphenated_is_sent_unchanged(monkeypatch, stored):
    """Better ABDM rejects it and says so than we silently reshape a bad value.

    Padding or truncating here would turn "this number is malformed" into
    "this number does not exist", which is a different and much worse answer.
    """
    client = _StubClient(body={"status": "ACTIVE"})
    mod = _install(monkeypatch, client)

    await mod._verify_with_gateway(stored)
    assert client.calls[0][2]["ABHANumber"] == stored


async def test_a_404_is_no_such_abha_not_an_outage(monkeypatch, caplog):
    """ABDM answers an absent ABHA with 404 ABDM-1114 "User not found".

    That is a successful lookup with a negative result. Logging it at WARNING
    beside a real decline is how a routine "this number is not registered"
    becomes an integration alarm — the same conflation that let a broken
    integration masquerade as a rural outage for months.
    """
    from app.integrations.abdm.client import AbdmRejected

    client = _StubClient(raises=AbdmRejected(404, {"error": {"code": "ABDM-1114"}}, "test-request-id"))
    mod = _install(monkeypatch, client)

    with caplog.at_level(logging.DEBUG, logger="healthdoc.abdm"):
        assert await mod._verify_with_gateway("91123456789012") is None

    records = [r for r in caplog.records if "ABHA" in r.getMessage()]
    assert records, "the 404 was not logged at all"
    assert all(r.levelno <= logging.INFO for r in records), (
        "an absent ABHA was logged as a warning; it is a normal answer"
    )


async def test_a_non_404_decline_is_still_a_warning(monkeypatch, caplog):
    """The distinction only helps if the other side of it survives."""
    from app.integrations.abdm.client import AbdmRejected

    client = _StubClient(raises=AbdmRejected(422, {"error": {"code": "ABDM-9999"}}, "test-request-id"))
    mod = _install(monkeypatch, client)

    with caplog.at_level(logging.DEBUG, logger="healthdoc.abdm"):
        assert await mod._verify_with_gateway("91123456789012") is None

    assert any(r.levelno >= logging.WARNING for r in caplog.records)
