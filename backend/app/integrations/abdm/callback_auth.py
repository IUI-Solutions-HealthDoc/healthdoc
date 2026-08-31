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
This is a shared-secret check, which is the weakest acceptable answer and is
here because the strong answer is not yet knowable: ABDM v3 signs callbacks,
and the exact signature scheme (header name, canonical string, key source) has
to be confirmed against the sandbox before it can be implemented without
guessing. `verify_callback` is the single place that will change when it is —
every route already depends on it, so the upgrade is one function body, not a
sweep. Until then a wrong guess at a signature algorithm would be worse than an
honest shared secret, because it would look like real cryptography.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, Request

from app.common.config import get_settings

log = logging.getLogger("healthdoc.abdm")

#: The header the gateway is configured to present. Named for what it is — a
#: shared secret — rather than borrowing ABDM's signature header name, which
#: would imply this performs a signature check.
CALLBACK_SECRET_HEADER = "X-HealthDoc-Callback-Secret"

_PLACEHOLDER = "change-me"


def is_configured() -> bool:
    secret = get_settings().abdm_callback_shared_secret
    return bool(secret) and secret != _PLACEHOLDER


#: Headers we already understand. Anything else arriving on a callback is worth
#: naming in the log exactly once — see _log_unrecognised_scheme.
_KNOWN_HEADERS = {
    "host", "user-agent", "accept", "accept-encoding", "connection",
    "content-type", "content-length", CALLBACK_SECRET_HEADER.lower(),
    "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host",
    "x-forwarded-port", "x-real-ip",
}


def _log_unrecognised_scheme(request: Request) -> None:
    """Name the headers a refused caller sent. NAMES ONLY, never values.

    The shared secret below is a placeholder for ABDM's real scheme, which
    signs its callbacks — and the exact scheme (header name, canonical string,
    key source) cannot be implemented without seeing one. This turns the first
    genuine sandbox callback into the answer instead of a silent 503: whatever
    ABDM signs with will show up here as an unrecognised header name.

    Values are deliberately excluded. A signature header carries key material,
    and this line is written at WARNING on a route reachable from the internet.
    """
    unknown = sorted(k for k in request.headers.keys() if k.lower() not in _KNOWN_HEADERS)
    if unknown:
        log.warning(
            "Refused ABDM callback carried unrecognised headers (names only): %s. "
            "If this came from the gateway, that is the signature scheme to "
            "implement in verify_callback.",
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
        raise HTTPException(503, {
            "code": "abdm_callbacks_not_configured",
            "message": "This server is not configured to accept ABDM callbacks.",
        })

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
