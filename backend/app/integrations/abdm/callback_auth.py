"""Authentication for inbound ABDM gateway callbacks.

WHY THIS FILE EXISTS AT ALL
---------------------------
Everything else in this integration is an outbound call we initiate and whose
answer we already expected. The HIP and HIU callback routes are the opposite:
unsolicited requests, from outside, that create consent artefacts and move
patient data. They are the most dangerous surface in an ABDM integration, and
they are the surface most likely to be left open — because during development
there is no gateway to authenticate against, and "allow it for now, tighten
before production" is an easy sentence to write.

This repository has already paid for that sentence five separate times (see
CLAUDE.md's list — `verify_aud: False` behind a "tighten later" comment being
the closest relative of this one). So:

    NOT CONFIGURED MEANS REFUSE, NOT ALLOW.

With `ABDM_CALLBACK_SHARED_SECRET` unset every callback route answers 503 and
says why. The integration is inert rather than open. That is a worse demo and a
correct system, and it is the only setting of this dial that cannot become an
incident.

WHAT THIS IS NOT
----------------
`verify_callback` below protects HealthDoc's legacy, private callback routes
with a shared secret.  The official ABDM v3 routes use the documented gateway
headers, strict recipient matching, timestamp freshness, replay coalescing and
transaction/consent checks instead.  The public ABDM collection does not define
a request-signature header, so this module deliberately does not claim those
headers are cryptographic proof of origin; source restrictions belong at the
public edge until NHA publishes such a scheme.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Header, HTTPException, Request

from app.common.config import get_settings
from app.common.redis import get_redis

log = logging.getLogger("healthdoc.abdm")

#: The header the gateway is configured to present. Named for what it is — a
#: shared secret — rather than borrowing ABDM's signature header name, which
#: would imply this performs a signature check.
CALLBACK_SECRET_HEADER = "X-HealthDoc-Callback-Secret"

_PLACEHOLDER = "change-me"
_MAX_CLOCK_SKEW = timedelta(minutes=10)
# This key is a short processing lock, not the durable idempotency record.  A
# gateway retry while the first request is still running is coalesced, but a
# failed handler must be allowed to run again.  The database transaction/state
# machines below the callback are the durable duplicate guard.
_REPLAY_TTL_SECONDS = 60


@dataclass(frozen=True)
class GatewayCallback:
    """Validated routing metadata for an official ABDM gateway callback."""

    request_id: str
    timestamp: datetime
    recipient_id: str
    replayed: bool = False
    #: The Redis processing-lock key claimed for this REQUEST-ID. Carried so a
    #: handler that FAILS can release it and let the gateway's retry re-run —
    #: see `_release_replay` and the `*_gateway_callback` dependencies below.
    replay_key: str | None = None


def is_configured() -> bool:
    secret = get_settings().abdm_callback_shared_secret
    return bool(secret) and secret != _PLACEHOLDER


#: Headers we already understand. Anything else arriving on a callback is worth
#: naming in the log exactly once — see _log_unrecognised_scheme.
_KNOWN_HEADERS = {
    "host",
    "user-agent",
    "accept",
    "accept-encoding",
    "connection",
    "content-type",
    "content-length",
    CALLBACK_SECRET_HEADER.lower(),
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-real-ip",
    # Cloudflare adds these to every request that passes through a tunnel, and
    # the sandbox deployment reaches ABDM through one. Found by running the
    # reachability probe against the public hostname and reading what this very
    # function logged: "cdn-loop, cf-connecting-ip, cf-ipcountry, cf-ray,
    # cf-visitor, cf-warp-tag-id" — six lines of noise that would sit directly
    # on top of the one header this log exists to surface.
    "cdn-loop",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cf-ray",
    "cf-visitor",
    "cf-warp-tag-id",
    "cf-worker",
    "cf-ew-via",
    "cf-request-id",
    # ABDM puts these on every callback — its own v3 Postman collection shows
    # REQUEST-ID, TIMESTAMP and X-CM-ID and nothing else on the HIP callback.
    # They were being reported as unrecognised, which is the opposite of useful:
    # this log exists to surface the ONE header we do not know, and we get a
    # single clean look at the first genuine callback to spot it in.
    "request-id",
    "timestamp",
    "x-cm-id",
    "x-hip-id",
    "x-hiu-id",
}


def _log_unrecognised_scheme(request: Request) -> None:
    """Name the headers a refused caller sent. NAMES ONLY, never values.

    This applies only to legacy private callbacks. It remains useful when a
    trusted caller and this deployment disagree about their configured secret,
    without logging any credential-bearing value.

    Values are deliberately excluded because this line is written at WARNING
    on a route reachable from the internet.
    """
    unknown = sorted(k for k in request.headers.keys() if k.lower() not in _KNOWN_HEADERS)
    if unknown:
        log.warning(
            "Refused legacy ABDM callback carried unrecognised headers " "(names only): %s.",
            ", ".join(unknown),
        )


async def verify_callback(
    request: Request,
    x_healthdoc_callback_secret: str | None = Header(default=None, alias=CALLBACK_SECRET_HEADER),
) -> None:
    """FastAPI dependency. Every inbound gateway route must depend on this.

    Raises 503 when this server cannot authenticate callers at all, and 401
    when it can and the caller failed. The two are deliberately different: the
    first is our misconfiguration and an operator needs to see it, the second
    is someone else's problem and must not be explained to them.
    """
    if not is_configured():
        # Logged at error, not warning: an ABDM callback arriving at a server
        # that cannot authenticate it means the gateway believes this endpoint
        # is live. That is an operational fault worth waking someone for.
        log.error(
            "Inbound ABDM callback refused — ABDM_CALLBACK_SHARED_SECRET is not "
            "set, so this server cannot tell the gateway from anyone else."
        )
        _log_unrecognised_scheme(request)
        raise HTTPException(
            503,
            {
                "code": "abdm_callbacks_not_configured",
                "message": "This server is not configured to accept ABDM callbacks.",
            },
        )

    expected = get_settings().abdm_callback_shared_secret or ""
    presented = x_healthdoc_callback_secret or ""

    # compare_digest, not ==. A byte-at-a-time comparison leaks the secret one
    # character per timing sample, and this endpoint is reachable from outside.
    if not hmac.compare_digest(presented, expected):
        # No detail. Whether the header was absent, short or simply wrong is
        # information an attacker can use to steer, and an honest gateway never
        # needs it.
        log.warning("Inbound ABDM callback rejected — shared secret did not match")
        _log_unrecognised_scheme(request)
        raise HTTPException(401, {"code": "unauthorised", "message": "Unauthorised"})


def _parse_timestamp(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            400, {"code": "invalid_timestamp", "message": "Invalid TIMESTAMP"}
        ) from exc
    if value.tzinfo is None:
        raise HTTPException(
            400, {"code": "invalid_timestamp", "message": "TIMESTAMP must include a timezone"}
        )
    return value.astimezone(UTC)


async def _verify_gateway_headers(
    request: Request,
    *,
    recipient_header: str | None,
    expected_recipient: str | None,
) -> GatewayCallback:
    """Validate ABDM's documented callback headers and reject replays.

    ABDM's published v3 callback contract does not send HealthDoc's private
    shared secret. It sends REQUEST-ID, TIMESTAMP, X-CM-ID and the addressed
    X-HIP-ID/X-HIU-ID. These checks enforce that contract without pretending a
    spoofable custom header is gateway authentication. Network allow-listing
    remains an edge control; transaction/consent checks remain the data control.
    """
    request_id = request.headers.get("REQUEST-ID")
    raw_timestamp = request.headers.get("TIMESTAMP")
    recipient = request.headers.get(recipient_header) if recipient_header else None
    cm_id = request.headers.get("X-CM-ID")
    if (
        not request_id
        or not raw_timestamp
        or not cm_id
        or (recipient_header is not None and not recipient)
    ):
        recipient_message = f", {recipient_header}" if recipient_header else ""
        raise HTTPException(
            400,
            {
                "code": "missing_abdm_headers",
                "message": f"REQUEST-ID, TIMESTAMP, X-CM-ID{recipient_message} are required",
            },
        )
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise HTTPException(
            400, {"code": "invalid_request_id", "message": "REQUEST-ID must be a UUID"}
        ) from exc

    settings = get_settings()
    if recipient_header and (not expected_recipient or expected_recipient == _PLACEHOLDER):
        raise HTTPException(
            503,
            {
                "code": "abdm_callbacks_not_configured",
                "message": f"{recipient_header} is not configured on this server",
            },
        )
    if recipient_header and not hmac.compare_digest(recipient or "", expected_recipient or ""):
        raise HTTPException(404, {"code": "unknown_service", "message": "Unknown ABDM service"})
    if not hmac.compare_digest(cm_id, settings.abdm_x_cm_id):
        raise HTTPException(401, {"code": "invalid_cm_id", "message": "Unauthorised"})

    timestamp = _parse_timestamp(raw_timestamp)
    if abs(datetime.now(UTC) - timestamp) > _MAX_CLOCK_SKEW:
        raise HTTPException(
            400,
            {
                "code": "stale_callback",
                "message": "Callback timestamp is outside the accepted window",
            },
        )

    replay_scope = recipient_header.lower() if recipient_header else "profile-share"
    replay_key = f"abdm:callback:{replay_scope}:{request.url.path}:{request_id}"
    try:
        first_seen = await get_redis().set(replay_key, "1", ex=_REPLAY_TTL_SECONDS, nx=True)
    except Exception as exc:  # fail closed when replay state is unavailable
        log.error("ABDM callback replay store unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            503,
            {
                "code": "callback_replay_store_unavailable",
                "message": "Callback verification is temporarily unavailable",
            },
        ) from exc
    return GatewayCallback(
        request_id=request_id,
        timestamp=timestamp,
        recipient_id=recipient or cm_id,
        replayed=not bool(first_seen),
        replay_key=replay_key,
    )


async def _release_replay(callback: GatewayCallback) -> None:
    """Drop the processing lock after a handler failed, so the retry re-runs.

    The lock claimed in `_verify_gateway_headers` exists to coalesce a gateway
    retry that arrives WHILE the first request is still in flight. It is not the
    durable duplicate guard — that is the database (transaction_id /
    consent_artefact_id are UNIQUE and the state machines upsert).

    The bug this closes: the lock was claimed on receipt, but a handler that
    then failed — its outbound acknowledgement raised, say, and `get_db` rolled
    the row back — left the lock standing for its full TTL. The gateway's retry,
    carrying the same REQUEST-ID, hit `if callback.replayed: return _accepted()`
    and was answered 202 without the work ever being redone. An unacknowledged
    consent grant is treated by ABDM as failed, so the grant silently took
    effect nowhere. Releasing the lock on failure lets the retry run for real;
    the DB guard keeps a genuine duplicate idempotent.
    """
    if callback.replayed or not callback.replay_key:
        return
    try:
        await get_redis().delete(callback.replay_key)
    except Exception:  # noqa: BLE001 — releasing a lock must never mask the handler error
        log.warning("Could not release the ABDM callback replay lock after a failed handler")


async def verify_hip_gateway_callback(request: Request) -> GatewayCallback:
    return await _verify_gateway_headers(
        request,
        recipient_header="X-HIP-ID",
        expected_recipient=get_settings().abdm_hip_id,
    )


async def verify_hiu_gateway_callback(request: Request) -> GatewayCallback:
    return await _verify_gateway_headers(
        request,
        recipient_header="X-HIU-ID",
        expected_recipient=get_settings().abdm_hiu_id,
    )


async def verify_profile_gateway_callback(request: Request) -> GatewayCallback:
    """Validate Scan-and-Share, whose published callback has no X-HIP-ID.

    The addressed HIP is carried in ``metaData.hipId`` and is checked by the
    route after Pydantic has validated the body.  Requiring a header which the
    gateway does not send made an otherwise valid profile share impossible.
    """
    return await _verify_gateway_headers(
        request,
        recipient_header=None,
        expected_recipient=None,
    )


# The dependencies the routes actually use. They wrap the coroutines above with
# release-on-failure. The coroutines stay callable and return a GatewayCallback
# (the unit tests call them directly); only the routed path gets the generator
# semantics that let a failed handler release its replay lock.


async def hip_gateway_callback(request: Request) -> AsyncIterator[GatewayCallback]:
    callback = await verify_hip_gateway_callback(request)
    try:
        yield callback
    except Exception:
        await _release_replay(callback)
        raise


async def hiu_gateway_callback(request: Request) -> AsyncIterator[GatewayCallback]:
    callback = await verify_hiu_gateway_callback(request)
    try:
        yield callback
    except Exception:
        await _release_replay(callback)
        raise


async def profile_gateway_callback(request: Request) -> AsyncIterator[GatewayCallback]:
    callback = await verify_profile_gateway_callback(request)
    try:
        yield callback
    except Exception:
        await _release_replay(callback)
        raise
