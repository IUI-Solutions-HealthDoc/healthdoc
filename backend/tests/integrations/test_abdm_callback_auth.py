"""Inbound ABDM callback authentication must fail CLOSED.

The behaviour under test is the one that is easy to get backwards during
development, when there is no gateway to authenticate against and letting
callbacks through is the only way to see the feature work. An unauthenticated
inbound route that writes consent artefacts and moves patient data is the worst
outcome in this integration, so "not configured" has to mean refuse.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from app.common.config import get_settings
from app.integrations.abdm import callback_auth


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request(**headers) -> Request:
    """A minimal ASGI request. verify_callback reads only the header names."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def _set_secret(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ABDM_CALLBACK_SHARED_SECRET", raising=False)
    else:
        monkeypatch.setenv("ABDM_CALLBACK_SHARED_SECRET", value)
    get_settings.cache_clear()


@pytest.mark.parametrize("unset", [None, "change-me"], ids=["absent", "placeholder"])
async def test_an_unconfigured_server_refuses_every_callback(monkeypatch, unset):
    """503 and nothing else. Not 200, not 'allowed in dev'."""
    _set_secret(monkeypatch, unset)
    assert callback_auth.is_configured() is False

    with pytest.raises(HTTPException) as caught:
        await callback_auth.verify_callback(_request(), x_healthdoc_callback_secret="anything")

    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "abdm_callbacks_not_configured"


async def test_a_wrong_secret_is_rejected(monkeypatch):
    _set_secret(monkeypatch, "the-real-secret")

    with pytest.raises(HTTPException) as caught:
        await callback_auth.verify_callback(_request(), x_healthdoc_callback_secret="not-it")

    assert caught.value.status_code == 401


async def test_a_missing_header_is_rejected_when_configured(monkeypatch):
    """Absent must not read as empty-equals-empty."""
    _set_secret(monkeypatch, "the-real-secret")

    with pytest.raises(HTTPException) as caught:
        await callback_auth.verify_callback(_request(), x_healthdoc_callback_secret=None)

    assert caught.value.status_code == 401


async def test_the_rejection_says_nothing_about_why(monkeypatch):
    """Whether the header was absent, short or simply wrong is steering
    information. An honest gateway never needs it."""
    _set_secret(monkeypatch, "the-real-secret")

    details = []
    for presented in (None, "", "x", "the-real-secre"):
        with pytest.raises(HTTPException) as caught:
            await callback_auth.verify_callback(_request(), x_healthdoc_callback_secret=presented)
        details.append(caught.value.detail)

    assert all(d == details[0] for d in details), "rejection detail varied by input"


async def test_the_matching_secret_passes(monkeypatch):
    _set_secret(monkeypatch, "the-real-secret")
    assert await callback_auth.verify_callback(_request(), x_healthdoc_callback_secret="the-real-secret") is None


def test_the_comparison_is_timing_safe():
    """Structural, not behavioural: a timing test is flaky and proves little.
    The AST is the honest check — `hmac.compare_digest` must be what compares
    the secret, because `==` on a secret leaks it one byte per sample and this
    endpoint is reachable from the internet.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(callback_auth))
    verify = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "verify_callback"
    )
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(verify)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert "hmac.compare_digest" in calls
    # And no plain equality against the secret anywhere in the function.
    assert not [
        node for node in ast.walk(verify)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        and any(
            isinstance(operand, ast.Name) and operand.id in {"expected", "presented"}
            for operand in [node.left, *node.comparators]
        )
    ], "the secret is compared with == somewhere in verify_callback"


async def test_a_refused_callback_names_the_headers_it_did_not_recognise(monkeypatch, caplog):
    """The first real ABDM callback is how we learn its signature scheme.

    The shared secret is a placeholder for ABDM's real scheme, and that scheme
    cannot be implemented without seeing one. So a refusal names the headers it
    did not recognise — whatever the gateway signs with shows up there instead
    of vanishing into a silent 503.
    """
    _set_secret(monkeypatch, "the-real-secret")

    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException):
            await callback_auth.verify_callback(
                _request(**{"X-Hmac-Signature": "abc123", "X-Gateway-Id": "sbx"}),
                x_healthdoc_callback_secret="wrong",
            )

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "x-hmac-signature" in logged.lower()
    assert "x-gateway-id" in logged.lower()


async def test_the_header_values_are_never_logged(monkeypatch, caplog):
    """Names only. A signature header carries key material, and this line is
    written on a route reachable from the internet."""
    _set_secret(monkeypatch, "the-real-secret")

    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException):
            await callback_auth.verify_callback(
                _request(**{"X-Hmac-Signature": "SUPER-SECRET-SIGNATURE-VALUE"}),
                x_healthdoc_callback_secret="wrong",
            )

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "SUPER-SECRET-SIGNATURE-VALUE" not in logged


async def test_ordinary_proxy_headers_are_not_reported_as_a_scheme(monkeypatch, caplog):
    """nginx adds X-Forwarded-*. Naming those every time would bury the one
    header that actually matters."""
    _set_secret(monkeypatch, "the-real-secret")

    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException):
            await callback_auth.verify_callback(
                _request(**{"X-Forwarded-For": "1.2.3.4", "Host": "example.org"}),
                x_healthdoc_callback_secret="wrong",
            )

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "unrecognised headers" not in logged


async def test_cloudflare_tunnel_headers_are_not_reported_as_a_scheme(monkeypatch, caplog):
    """The sandbox reaches ABDM through a Cloudflare tunnel.

    Found by running the reachability probe against the public hostname and
    reading what verify_callback logged: six cf-* headers, which would sit
    directly on top of the one header this log exists to surface. Same failure
    mode as X-Forwarded-* — noise that buries the signal — but only visible
    once the thing was deployed behind a real tunnel.
    """
    _set_secret(monkeypatch, "the-real-secret")

    cloudflare = {
        "CDN-Loop": "cloudflare", "CF-Connecting-IP": "1.2.3.4",
        "CF-IPCountry": "IN", "CF-RAY": "abc123-DEL",
        "CF-Visitor": '{"scheme":"https"}', "CF-Warp-Tag-Id": "x",
    }
    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException):
            await callback_auth.verify_callback(
                _request(**cloudflare), x_healthdoc_callback_secret="wrong"
            )
    assert "unrecognised headers" not in " ".join(r.getMessage() for r in caplog.records)


async def test_a_real_signature_header_still_surfaces_through_the_tunnel(monkeypatch, caplog):
    """Filtering the noise must not filter the signal."""
    _set_secret(monkeypatch, "the-real-secret")

    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException):
            await callback_auth.verify_callback(
                _request(**{"CF-RAY": "abc123-DEL", "X-Hmac-Signature": "sig"}),
                x_healthdoc_callback_secret="wrong",
            )
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "x-hmac-signature" in logged.lower()
    assert "cf-ray" not in logged.lower()
