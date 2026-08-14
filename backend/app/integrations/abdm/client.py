"""The one way to talk to the ABDM gateway.

Everything ABDM — ABHA enrolment (M1), ABHA linking (M2), care-context
linking and data exchange (M3) — goes through this client. Nothing else in
the codebase should construct an httpx call to `abdm_gateway_base_url`.

WHAT THIS SOLVES
----------------
ABDM authenticates with a short-lived session token obtained from client
credentials. Every subsequent call carries that token plus three headers the
gateway rejects requests without: REQUEST-ID, TIMESTAMP and X-CM-ID. Getting
any of them wrong produces a 401 or a 400 with a body that says very little.

Before this existed there was exactly one gateway call in the repo —
`_verify_with_gateway` in abdm/identity/router.py — and it obtained no token
at all. It works today only because the sandbox tolerates it; it will not
work against anything real.

DESIGN NOTES, in the order people ask about them
------------------------------------------------
**Token cache is per-process, not Redis.** Each worker fetching its own token
is explicitly allowed, and a Redis dependency here would add a failure mode to
the path that every ABDM call depends on. The cost is one extra session call
per worker per token lifetime. If that ever matters, `_TokenCache` is the seam
to replace — nothing else needs to change.

**Refresh is guarded by a lock.** Without it, N concurrent requests arriving
on an expired token all fetch a new one. The lock means one fetches and the
rest wait on it.

**Expiry has a safety margin.** A token that expires between our check and the
gateway's receipt produces a 401 that looks like a credentials problem. We
treat a token as expired `_EXPIRY_MARGIN_SECONDS` early.

**One 401 retry, not more.** ABDM can revoke a token before its stated expiry.
A single forced refresh covers that. A second 401 means the credentials are
wrong, and retrying a credentials problem is how you get an account locked.

**Errors are a taxonomy, not one exception.** Callers need to distinguish "the
gateway is down, degrade gracefully and mark the record unverified" from "ABDM
rejected this payload, fix it" from "our credentials are wrong, page someone".
`identity/router.py` already degrades on the first; it can't currently tell it
apart from the third.

**No PHI in logs, ever.** ABDM payloads carry ABHA numbers, Aadhaar-derived
identifiers and clinical bundles. This module logs status codes, REQUEST-IDs
and durations. It never logs a request or response body, including on error.

**REQUEST-ID is returned to the caller.** `fhir_bundle_transactions` has an
`abdm_request_id` column (0026) precisely so a transmission can be traced back
to the gateway's own logs during certification. The caller gets the id we sent
so it can store it.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app.common.config import get_settings

log = logging.getLogger(__name__)

# Treat a token as expired this many seconds before it actually is, so a call
# in flight doesn't land after expiry.
_EXPIRY_MARGIN_SECONDS = 60

# Sandbox is slow and occasionally very slow. Connect fast, read patiently:
# a timeout here surfaces as "gateway unavailable" and the caller degrades,
# so being too aggressive turns transient slowness into unverified records.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

_PLACEHOLDER = "change-me"


class AbdmError(Exception):
    """Base for every ABDM failure. Catch this to treat them alike."""


class AbdmNotConfigured(AbdmError):
    """Credentials are still the .env.example placeholders.

    Raised eagerly rather than letting a request go out with 'change-me' as a
    client id, which the gateway answers with a 401 that reads like a code bug.
    """


class AbdmAuthError(AbdmError):
    """Gateway rejected our credentials, or rejected a freshly minted token.

    Not retryable. Means the client id/secret are wrong, expired, or the
    facility's registration has lapsed — a human problem, not a transient one.
    """


class AbdmUnavailable(AbdmError):
    """Network failure, timeout, or a 5xx. Transient — degrade and retry later.

    This is the one callers should handle by storing the record with
    identity_status='identity_unverified' rather than failing the request:
    a patient in front of a receptionist should not be blocked by ABDM being
    down.
    """


class AbdmRejected(AbdmError):
    """Gateway understood the request and refused it (4xx other than 401/403).

    Carries the status and the gateway's error body, which is the only place
    ABDM explains itself. Callers may surface `detail` to the operator —
    it describes the request, not the patient.
    """

    def __init__(self, status_code: int, detail: Any, request_id: str) -> None:
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id
        super().__init__(f"ABDM rejected request {request_id}: {status_code} {detail}")


@dataclass
class AbdmResponse:
    """A successful gateway response, plus the REQUEST-ID we sent.

    The id belongs in fhir_bundle_transactions.abdm_request_id — it is how a
    transmission is traced in ABDM's own logs during certification.
    """

    status_code: int
    body: Any
    request_id: str


class _TokenCache:
    """Per-process session token with expiry. The seam to swap for Redis."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def get_if_fresh(self) -> str | None:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        return None

    def set(self, token: str, expires_in_seconds: float) -> None:
        self._token = token
        self._expires_at = time.monotonic() + max(
            0.0, expires_in_seconds - _EXPIRY_MARGIN_SECONDS
        )

    def clear(self) -> None:
        self._token = None
        self._expires_at = 0.0


class AbdmClient:
    """Session-authenticated ABDM gateway client.

    Construct one and reuse it — it owns a connection pool and a token cache.
    `get_abdm_client()` returns the process-wide instance; tests pass their own
    `transport` to intercept without touching the network.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        cm_id: str | None = None,
        session_path: str = "/v3/sessions",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.abdm_gateway_base_url).rstrip("/")
        self.client_id = client_id or settings.abdm_client_id
        self.client_secret = client_secret or settings.abdm_client_secret
        # 'sbx' is the sandbox consent-manager id; production is 'abdm'.
        self.cm_id = cm_id or getattr(settings, "abdm_x_cm_id", "sbx")
        self.session_path = session_path
        self._tokens = _TokenCache()
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or _DEFAULT_TIMEOUT,
            transport=transport,
        )

    # ------------------------------------------------------------------ config
    @property
    def is_configured(self) -> bool:
        """False while the .env placeholders are in place.

        Call sites can use this to keep an endpoint registered but inert,
        rather than deciding at import time whether ABDM exists.
        """
        return all(
            v and v != _PLACEHOLDER for v in (self.client_id, self.client_secret)
        )

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise AbdmNotConfigured(
                "ABDM_CLIENT_ID / ABDM_CLIENT_SECRET are unset or still 'change-me'. "
                "Set them from the sandbox registration before calling the gateway."
            )

    # ------------------------------------------------------------------- token
    async def _fetch_token(self) -> tuple[str, float]:
        """POST the client credentials, return (token, lifetime_seconds).

        Deliberately does NOT go through `request()` — that would recurse,
        since request() needs a token.
        """
        request_id = str(uuid.uuid4())
        try:
            resp = await self._http.post(
                self.session_path,
                json={
                    "clientId": self.client_id,
                    "clientSecret": self.client_secret,
                    "grantType": "client_credentials",
                },
                headers={
                    "REQUEST-ID": request_id,
                    "TIMESTAMP": _timestamp(),
                    "X-CM-ID": self.cm_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # No body logged: even an auth failure body can echo the client id.
            log.warning("ABDM session request %s failed at transport: %s",
                        request_id, type(exc).__name__)
            raise AbdmUnavailable("ABDM gateway unreachable for session") from exc

        if resp.status_code in (401, 403):
            log.error("ABDM rejected client credentials (session %s, %s)",
                      request_id, resp.status_code)
            raise AbdmAuthError(
                f"ABDM rejected client credentials ({resp.status_code})"
            )
        if resp.status_code >= 500:
            log.warning("ABDM session %s returned %s", request_id, resp.status_code)
            raise AbdmUnavailable(f"ABDM session endpoint returned {resp.status_code}")
        if resp.status_code >= 400:
            raise AbdmRejected(resp.status_code, _safe_body(resp), request_id)

        body = _safe_body(resp)
        if not isinstance(body, Mapping):
            raise AbdmUnavailable("ABDM session response was not a JSON object")

        token = body.get("accessToken") or body.get("access_token")
        if not token:
            # Do not log `body` — it is the token envelope.
            raise AbdmUnavailable("ABDM session response contained no accessToken")

        expires_in = body.get("expiresIn") or body.get("expires_in") or 0
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 0.0
        if expires_in <= 0:
            # ABDM has historically returned 1800. If it says nothing, assume a
            # short life rather than a long one — a stale token costs a retry,
            # a wrongly-long one costs every call until it expires.
            expires_in = 300.0

        log.info("ABDM session acquired (request %s, ttl %.0fs)", request_id, expires_in)
        return token, expires_in

    async def _token(self, *, force_refresh: bool = False) -> str:
        self._require_configured()
        if not force_refresh:
            cached = self._tokens.get_if_fresh()
            if cached:
                return cached

        async with self._tokens._lock:
            # Someone may have refreshed while we waited for the lock.
            if not force_refresh:
                cached = self._tokens.get_if_fresh()
                if cached:
                    return cached
            token, ttl = await self._fetch_token()
            self._tokens.set(token, ttl)
            return token

    # ----------------------------------------------------------------- request
    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        extra_headers: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> AbdmResponse:
        """Make an authenticated gateway call.

        `request_id` may be supplied so a caller can reuse the same id across a
        retry — ABDM treats REQUEST-ID as the idempotency key for several
        endpoints, so a genuine retry should carry the original.
        """
        self._require_configured()
        rid = request_id or str(uuid.uuid4())

        token = await self._token()
        resp = await self._send(method, path, json, token, rid, extra_headers)

        if resp.status_code == 401:
            # Revoked early, or expired between our margin and the gateway.
            # Exactly one forced refresh; a second 401 is a credentials fault.
            log.info("ABDM 401 on %s — refreshing session and retrying once", rid)
            token = await self._token(force_refresh=True)
            resp = await self._send(method, path, json, token, rid, extra_headers)
            if resp.status_code == 401:
                self._tokens.clear()
                raise AbdmAuthError(
                    "ABDM returned 401 with a freshly issued token — check credentials"
                )

        if resp.status_code == 403:
            raise AbdmAuthError(f"ABDM returned 403 for {method} {path}")
        if resp.status_code >= 500:
            raise AbdmUnavailable(f"ABDM returned {resp.status_code} for {method} {path}")
        if resp.status_code >= 400:
            raise AbdmRejected(resp.status_code, _safe_body(resp), rid)

        return AbdmResponse(resp.status_code, _safe_body(resp), rid)

    async def _send(
        self,
        method: str,
        path: str,
        json_body: Any,
        token: str,
        request_id: str,
        extra_headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "REQUEST-ID": request_id,
            "TIMESTAMP": _timestamp(),
            "X-CM-ID": self.cm_id,
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        started = time.monotonic()
        try:
            resp = await self._http.request(method, path, json=json_body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("ABDM %s %s (request %s) failed at transport: %s",
                        method, path, request_id, type(exc).__name__)
            raise AbdmUnavailable(f"ABDM gateway unreachable for {method} {path}") from exc

        # Status and duration only. Never the body — it carries PHI.
        log.info("ABDM %s %s -> %s (request %s, %.0fms)",
                 method, path, resp.status_code, request_id,
                 (time.monotonic() - started) * 1000)
        return resp

    async def aclose(self) -> None:
        await self._http.aclose()


def _timestamp() -> str:
    """ABDM wants ISO-8601 UTC with a trailing Z, to milliseconds."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _safe_body(resp: httpx.Response) -> Any:
    """Parse JSON if we can; fall back to text. Never raises."""
    try:
        return resp.json()
    except Exception:
        return resp.text


_client: AbdmClient | None = None


def get_abdm_client() -> AbdmClient:
    """Process-wide client. Reused so the pool and token cache are shared."""
    global _client
    if _client is None:
        _client = AbdmClient()
    return _client


def reset_abdm_client() -> None:
    """Drop the singleton. For tests, and for a credentials reload."""
    global _client
    _client = None
