"""Short-lived OTP proof for ABDM patient-initiated care-context linking.

ABDM v3 asks a HIP to use mediated authentication during user-initiated
linking.  The gateway returns the code the patient entered on the confirm
callback; accepting that callback without checking the code would let anyone
who can reach it claim a patient's care contexts.

Only an HMAC digest and an attempt counter live in Redis, both under a ten
minute TTL.  The clear code exists long enough to be sent to the configured
SMS relay and is never logged, returned by an API, or written to Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import httpx

from app.common.config import get_settings
from app.common.redis import get_redis
from app.common.security import _get_hmac_key

OTP_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
_KEY_PREFIX = "abdm:link-otp"


class LinkOtpUnavailable(RuntimeError):
    """The deployment cannot deliver a mediated-linking OTP."""


class LinkOtpInvalid(ValueError):
    """The OTP is wrong but the attempt window is still open."""


class LinkOtpExpired(ValueError):
    """The OTP is absent, expired, or locked after too many attempts."""


def _key(link_ref_number: str) -> str:
    return f"{_KEY_PREFIX}:{link_ref_number}"


def _digest(link_ref_number: str, otp: str) -> str:
    return hmac.new(
        _get_hmac_key(),
        f"{link_ref_number}:{otp}".encode(),
        hashlib.sha256,
    ).hexdigest()


def masked_mobile(mobile: str) -> str:
    digits = "".join(character for character in mobile if character.isdigit())
    if len(digits) < 10 or len(digits) > 15:
        raise LinkOtpUnavailable("The patient has no usable mobile number for linking")
    return f"******{digits[-4:]}"


async def _deliver(*, mobile: str, otp: str) -> None:
    """Send through the deployment's HTTPS SMS relay contract."""
    settings = get_settings()
    url = settings.abdm_link_otp_delivery_url
    if not url:
        raise LinkOtpUnavailable("ABDM_LINK_OTP_DELIVERY_URL is not configured")
    if settings.environment.strip().lower() in {"prod", "production"} and not url.startswith(
        "https://"
    ):
        raise LinkOtpUnavailable("The ABDM linking OTP relay must use HTTPS in production")

    headers = {"Content-Type": "application/json"}
    if settings.abdm_link_otp_delivery_token:
        headers["Authorization"] = f"Bearer {settings.abdm_link_otp_delivery_token}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "recipient": mobile,
                    "message": (
                        f"Your HealthDoc verification code is {otp}. "
                        "It expires in 10 minutes. Do not share it."
                    ),
                    "purpose": "abdm_care_context_link",
                    "expiresInSeconds": OTP_TTL_SECONDS,
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LinkOtpUnavailable("The configured SMS relay did not accept the OTP") from exc


async def issue(*, link_ref_number: str, mobile: str) -> str:
    """Create, retain only a digest, deliver, and return a masked hint."""
    hint = masked_mobile(mobile)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    redis = get_redis()
    await redis.set(
        _key(link_ref_number),
        json.dumps({"digest": _digest(link_ref_number, otp), "attempts": 0}),
        ex=OTP_TTL_SECONDS,
    )
    try:
        await _deliver(mobile=mobile, otp=otp)
    except Exception:
        await redis.delete(_key(link_ref_number))
        raise
    return hint


_VERIFY_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then return -1 end
local state = cjson.decode(raw)
if tonumber(state.attempts) >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  return -1
end
if state.digest == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
state.attempts = tonumber(state.attempts) + 1
if state.attempts >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  return -1
end
redis.call('SET', KEYS[1], cjson.encode(state), 'KEEPTTL')
return 0
"""


async def verify(*, link_ref_number: str, otp: str) -> None:
    """Atomically verify one code and enforce the bounded attempt count."""
    # Invalid syntax still spends an attempt; it is not a free oracle.
    presented = _digest(link_ref_number, otp)
    result = await get_redis().eval(
        _VERIFY_SCRIPT,
        1,
        _key(link_ref_number),
        presented,
        str(MAX_ATTEMPTS),
    )
    if int(result) == 1:
        return
    if int(result) == 0:
        raise LinkOtpInvalid("Incorrect OTP")
    raise LinkOtpExpired("The OTP expired or too many attempts were made")
