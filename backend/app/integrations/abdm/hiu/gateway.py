"""Outbound HIU calls to the ABDM gateway — the half M3 was missing.

Same split as `hip/gateway.py`: wire protocol only, no database session, no
policy. `service.py` decides whether a consent may be requested and what to do
with a bundle; this module knows what ABDM's JSON looks like.

Every shape comes from ABDM's official v3 Postman collection.

THE DATA-FLOW HANDSHAKE, BECAUSE IT IS NOT OBVIOUS
--------------------------------------------------
An HIU does not fetch records. It asks, and records arrive later at a URL it
nominated:

    request_health_information(dataPushUrl=..., dhPublicKey=...)
        -> gateway -> HIP
    HIP encrypts a bundle to OUR public key and POSTs it to dataPushUrl
        -> our /abdm/hiu/callbacks/health-information/transfer

So three things have to be true at the moment of the request, and each fails
silently rather than loudly if it is not:

  * `dataPushUrl` must be reachable from the internet. A private address is
    accepted by the gateway and the transfer simply never arrives.
  * The X25519 public key we send must correspond to a private key we still
    hold when the bundle lands, possibly minutes later. `service.py` persists
    it; this module only carries it.
  * `nonce` must be fresh per request. It is an input to the shared-secret
    derivation, so reusing one across requests makes two bundles decryptable
    with the same key material.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.common.config import get_settings
from app.integrations.abdm.client import AbdmResponse, get_abdm_client
from app.integrations.abdm.hip.gateway import HI_TYPES, validate_hi_types

log = logging.getLogger("healthdoc.abdm")

__all__ = [
    "HI_TYPES",
    "HiuIdentityNotConfigured",
    "DataPushUrlNotConfigured",
    "hiu_id",
    "data_push_url",
    "request_consent",
    "check_consent_request_status",
    "fetch_consent_artefact",
    "request_health_information",
    "acknowledge_consent_notification",
    "notify_hi_receipt",
]

_PLACEHOLDER = "change-me"

#: ABDM's purpose vocabulary. CAREMGT is the one a hospital pulling records for
#: treatment uses; the others exist and are not offered here because using the
#: wrong purpose code on a consent request is a compliance problem, not a bug.
PURPOSE_CARE_MANAGEMENT = {
    "code": "CAREMGT",
    "text": "Care Management",
    "refUri": "www.abdm.gov.in",
}


class HiuIdentityNotConfigured(RuntimeError):
    """`ABDM_HIU_ID` is unset, so we cannot say who is asking."""


class DataPushUrlNotConfigured(RuntimeError):
    """`ABDM_HIU_CALLBACK_BASE_URL` is unset.

    Refusing beats sending a request with an unreachable push address: the
    gateway accepts it, the HIP encrypts a real patient's records, the POST
    fails somewhere we cannot see, and the only symptom is a transfer that
    never arrives.
    """


def hiu_id() -> str:
    value = get_settings().abdm_hiu_id
    if not value or value == _PLACEHOLDER:
        raise HiuIdentityNotConfigured(
            "ABDM_HIU_ID is not set. Register a service with "
            "PUT /api/hiecm/gateway/v3/bridge-service and set the id it returns."
        )
    return value


def data_push_url() -> str:
    """Where HIPs POST encrypted bundles for us."""
    base = get_settings().abdm_hiu_callback_base_url
    if not base or base == _PLACEHOLDER:
        raise DataPushUrlNotConfigured(
            "ABDM_HIU_CALLBACK_BASE_URL is not set, so there is nowhere for a "
            "HIP to deliver records."
        )
    return f"{base.rstrip('/')}/api/v1/abdm/hiu/callbacks/health-information/transfer"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _iso(value: datetime) -> str:
    """ABDM wants UTC with a literal Z, not the `+00:00` isoformat produces."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def _post(
    path: str,
    payload: Mapping[str, Any] | None,
    *,
    extra_headers: Mapping[str, str] | None = None,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    rid = request_id or str(uuid.uuid4())
    client = get_abdm_client()
    response = await client.request(
        "POST",
        path,
        json=dict(payload) if payload is not None else None,
        extra_headers=extra_headers,
        request_id=rid,
    )
    # Path and status only — these bodies carry ABHA addresses and consent ids.
    log.info("ABDM HIU call %s -> %s (request_id=%s)", path, response.status_code, rid)
    return rid, response


# =============================================================================
# Consent
# =============================================================================

async def request_consent(
    *,
    abha_address: str,
    hi_types: Sequence[str],
    date_from: datetime,
    date_to: datetime,
    expiry: datetime,
    purpose: Mapping[str, str] | None = None,
    hip_id: str | None = None,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Ask the consent manager for access to a patient's records.

    Returns immediately with an acknowledgement; the patient then approves or
    denies in their ABHA app and the outcome reaches us on the HIU consent
    callback, possibly days later. Persist the returned request id.

    `hip_id` scopes the request to one provider. None means "any HIP", which is
    what a hospital pulling a patient's history wants and what ABDM's own
    example sends (`"hip": null`).
    """
    settings = get_settings()
    validate_hi_types(hi_types)
    if date_to < date_from:
        raise ValueError("date_to is before date_from")
    return await _post(
        settings.abdm_path_hiu_consent_request_init,
        {
            "consent": {
                "hip": {"id": hip_id} if hip_id else None,
                "hiu": {"id": hiu_id()},
                "hiTypes": list(hi_types),
                "patient": {"id": abha_address},
                "purpose": dict(purpose or PURPOSE_CARE_MANAGEMENT),
                "permission": {
                    "accessMode": "VIEW",
                    "dateRange": {"from": _iso(date_from), "to": _iso(date_to)},
                    "dataEraseAt": _iso(expiry),
                    # value/repeats 0 means "no recurring pull" — a one-off
                    # read. A non-zero frequency asks the CM for standing
                    # access, which is a different consent and a different
                    # conversation with the patient.
                    "frequency": {"unit": "HOUR", "value": 0, "repeats": 0},
                },
            }
        },
        request_id=request_id,
    )


async def check_consent_request_status(
    *, consent_request_id: str, request_id: str | None = None
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Poll a consent request.

    A backstop, not the primary path: the grant arrives on a callback. This
    exists because a callback that never lands is otherwise indistinguishable
    from a patient who has not answered yet.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hiu_consent_request_status,
        {"consentRequestId": consent_request_id},
        extra_headers={"X-HIU-ID": hiu_id()},
        request_id=request_id,
    )


async def fetch_consent_artefact(
    *, consent_id: str, request_id: str | None = None
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Fetch the granted artefact by id.

    The artefact — not the request, and not the notification — is what states
    the permitted date range, HI types and expiry. Acting on the request we
    sent rather than the artefact we were granted is how an HIU ends up reading
    outside its consent.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hiu_consent_fetch,
        {"consentId": consent_id},
        extra_headers={"X-HIU-ID": hiu_id()},
        request_id=request_id,
    )


async def acknowledge_consent_notification(
    *,
    consent_id: str,
    gateway_request_id: str,
    status: str = "OK",
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Acknowledge a consent notification.

    Note the acknowledgement is a LIST here and an object on the HIP side. That
    asymmetry is ABDM's, not ours, and it is the kind of detail that turns into
    a validation error naming a field that looks correct.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hiu_on_consent_notify,
        {
            "acknowledgement": [{"status": status, "consentId": consent_id}],
            "response": {"requestId": gateway_request_id},
        },
        request_id=request_id,
    )


# =============================================================================
# Data flow
# =============================================================================

async def request_health_information(
    *,
    consent_id: str,
    date_from: datetime,
    date_to: datetime,
    dh_public_key: str,
    key_expiry: datetime,
    nonce: str,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Ask for the records a consent artefact permits.

    `dh_public_key` is our X25519 public key, base64, whose private half must
    still be retrievable when the bundle arrives — see the module docstring.
    `nonce` must be fresh per request.

    The date range must sit inside the artefact's range. The gateway does check
    this, but a range wider than the consent is refused with a generic message,
    so callers should narrow it from the artefact rather than from the original
    request.
    """
    settings = get_settings()
    if date_to < date_from:
        raise ValueError("date_to is before date_from")
    return await _post(
        settings.abdm_path_hiu_hi_request,
        {
            "hiRequest": {
                "consent": {"id": consent_id},
                "dateRange": {"from": _iso(date_from), "to": _iso(date_to)},
                "dataPushUrl": data_push_url(),
                "keyMaterial": {
                    "cryptoAlg": "ECDH",
                    "curve": "Curve25519",
                    "dhPublicKey": {
                        "expiry": _iso(key_expiry),
                        "parameters": "Curve25519/32byte random key",
                        "keyValue": dh_public_key,
                    },
                    "nonce": nonce,
                },
            }
        },
        extra_headers={"X-HIU-ID": hiu_id()},
        request_id=request_id,
    )


async def notify_hi_receipt(
    *,
    consent_id: str,
    transaction_id: str,
    session_status: str,
    hip_id: str,
    status_responses: Sequence[Mapping[str, str]],
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIU -> gateway. Confirm what we received.

    Same endpoint the HIP notifies on; `notifier.type` and `sessionStatus` are
    what distinguish the two sides. Without it the gateway shows the patient a
    transfer stuck at "sent" forever.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_hi_notify,
        {
            "notification": {
                "consentId": consent_id,
                "transactionId": transaction_id,
                "doneAt": _now_iso(),
                "notifier": {"type": "HIU", "id": hiu_id()},
                "statusNotification": {
                    "sessionStatus": session_status,
                    "hipId": hip_id,
                    "statusResponses": [dict(s) for s in status_responses],
                },
            }
        },
        extra_headers={"X-HIU-ID": hiu_id()},
        request_id=request_id,
    )
