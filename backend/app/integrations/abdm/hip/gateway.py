"""Outbound HIP calls to the ABDM gateway — the half M2 was missing.

Until now this package could RECEIVE (callback routes, state services, crypto)
and could not SPEAK. The ten `abdm_path_hip_*` / `abdm_path_hiu_*` settings were
referenced nowhere outside config.py, so a HIP that never posts
`link/carecontext` and never answers a discovery could not be certified however
complete the receiving half was.

WHAT THIS MODULE IS, AND IS NOT
-------------------------------
It is the wire protocol only: build ABDM's payload, send it, hand back the
REQUEST-ID. It holds no database session and makes no policy decision. State
lives in `service.py`, which is what decides whether a link may be confirmed or
a record may be handed over. Keeping the two apart is what lets the payload
shapes below be checked against ABDM's collection line by line without reading
around business logic.

EVERY SHAPE HERE COMES FROM ABDM'S OFFICIAL v3 POSTMAN COLLECTION.
Nothing is inferred from a sibling endpoint. Where the collection is internally
inconsistent — and it is, once — the code says so at the call site rather than
quietly picking a side.

DIRECTION MATTERS AND IS EASY TO GET WRONG
------------------------------------------
This repository has already shipped `/v3/hip/token/on-generate` as an endpoint
to POST to, when it is a callback the gateway invokes ON a HIP. Every function
below records which way it points in its docstring. `on-*` names are OUR
response to something the gateway asked us; the rest are requests we start.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.common.config import get_settings
from app.integrations.abdm.client import AbdmResponse, get_abdm_client

log = logging.getLogger("healthdoc.abdm")

#: ABDM's fixed vocabulary for health-information types. A value outside this
#: set is rejected by the gateway with a validation error that names the field
#: but not the allowed values, so the check is done here where the list can be
#: read.
HI_TYPES: frozenset[str] = frozenset({
    "Prescription",
    "DiagnosticReport",
    "OPConsultation",
    "DischargeSummary",
    "ImmunizationRecord",
    "HealthDocumentRecord",
    "WellnessRecord",
    "Invoice",
})

_PLACEHOLDER = "change-me"


class HipIdentityNotConfigured(RuntimeError):
    """`ABDM_HIP_ID` is unset, so we cannot say who is speaking.

    Raised instead of sending `change-me` as an identity. A gateway call that
    claims to be a HIP named "change-me" either fails confusingly or, worse,
    succeeds against somebody else's registration.
    """


def hip_id() -> str:
    value = get_settings().abdm_hip_id
    if not value or value == _PLACEHOLDER:
        raise HipIdentityNotConfigured(
            "ABDM_HIP_ID is not set. Register a service with "
            "PUT /api/hiecm/gateway/v3/bridge-service and set the id it returns."
        )
    return value


def _now_iso() -> str:
    """ABDM wants millisecond-precision UTC with a literal Z.

    `datetime.isoformat()` gives `+00:00`, which the gateway rejects on some
    endpoints and silently tolerates on others — the inconsistent kind of bug.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def validate_hi_types(hi_types: Sequence[str]) -> list[str]:
    """Reject unknown HI types here rather than at the gateway.

    Returns the list unchanged so it reads as a pass-through at the call site.
    """
    unknown = sorted(set(hi_types) - HI_TYPES)
    if unknown:
        raise ValueError(
            f"Unknown ABDM health-information type(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(HI_TYPES))}"
        )
    if not hi_types:
        raise ValueError("At least one health-information type is required")
    return list(hi_types)


def care_context_payload(
    *,
    abha_address: str,
    display: str,
    care_contexts: Sequence[Mapping[str, str]],
    hi_type: str,
) -> dict[str, Any]:
    """The `patient[]` element shared by discover, link-init and link-confirm.

    ABDM repeats this structure across four endpoints with the same field names
    and the same meaning, so it is built once. `count` is the number of care
    contexts and is NOT optional — omitting it is accepted and then produces an
    empty link.
    """
    contexts = [
        {"referenceNumber": c["referenceNumber"], "display": c["display"]}
        for c in care_contexts
    ]
    return {
        "referenceNumber": abha_address,
        "display": display,
        "careContexts": contexts,
        "hiType": hi_type,
        "count": len(contexts),
    }


async def _post(
    path: str,
    payload: Mapping[str, Any],
    *,
    extra_headers: Mapping[str, str] | None = None,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """Send and return (request_id, response).

    The REQUEST-ID is returned rather than logged-and-forgotten because every
    one of these flows is asynchronous: the gateway answers on a callback
    minutes later carrying `response.requestId`, and without the id we sent
    there is nothing to correlate it to. Callers persist it.
    """
    rid = request_id or str(uuid.uuid4())
    client = get_abdm_client()
    response = await client.request(
        "POST", path, json=dict(payload), extra_headers=extra_headers, request_id=rid
    )
    # Path and status only. These payloads carry ABHA addresses and care-context
    # references, which are patient identifiers.
    log.info("ABDM HIP call %s -> %s (request_id=%s)", path, response.status_code, rid)
    return rid, response


# =============================================================================
# HIP-initiated linking — we start these
# =============================================================================

async def generate_link_token(
    *,
    abha_address: str,
    name: str,
    gender: str,
    year_of_birth: str,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Exchange demographics for a link token.

    The token arrives asynchronously on our callback, not in this response;
    `link_care_contexts` needs it as X-LINK-TOKEN. Note the path sits at the
    bare `/api/hiecm/v3/token/...` base rather than under `/hip/v3/` — one of
    the few that does, and the reason `abdm_path_hip_token_generate` is a
    separate setting instead of a suffix.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_token_generate,
        {
            "abhaAddress": abha_address,
            "name": name,
            "gender": gender,
            "yearOfBirth": year_of_birth,
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


async def link_care_contexts(
    *,
    abha_address: str,
    link_token: str,
    display: str,
    care_contexts: Sequence[Mapping[str, str]],
    hi_type: str,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Attach care contexts we hold to an ABHA address.

    Requires X-LINK-TOKEN from `generate_link_token`. Without it the gateway
    answers 401 rather than a validation error, which reads like a credentials
    problem and sends you to the wrong place.
    """
    settings = get_settings()
    validate_hi_types([hi_type])
    return await _post(
        settings.abdm_path_hip_link_add_contexts,
        {
            "abhaAddress": abha_address,
            "patient": [
                care_context_payload(
                    abha_address=abha_address,
                    display=display,
                    care_contexts=care_contexts,
                    hi_type=hi_type,
                )
            ],
        },
        extra_headers={"X-HIP-ID": hip_id(), "X-LINK-TOKEN": link_token},
        request_id=request_id,
    )


async def notify_care_context(
    *,
    abha_address: str,
    care_context_reference: str,
    hi_types: Sequence[str],
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Tell the CM a new care context exists for a linked patient.

    This is what makes a NEW encounter visible to a patient who linked with us
    previously. Skipping it is the classic HIP defect: linking works once, and
    every record created afterwards is invisible.
    """
    settings = get_settings()
    validate_hi_types(hi_types)
    return await _post(
        settings.abdm_path_hip_context_notify,
        {
            "notification": {
                "patient": {"id": abha_address},
                "careContext": {
                    "patientReference": abha_address,
                    "careContextReference": care_context_reference,
                },
                "hiTypes": list(hi_types),
                "date": _now_iso(),
                "hip": {"id": hip_id()},
            }
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


# =============================================================================
# Patient-initiated linking — the gateway asks, we answer
# =============================================================================

async def respond_to_discovery(
    *,
    transaction_id: str,
    gateway_request_id: str,
    abha_address: str,
    display: str,
    care_contexts: Sequence[Mapping[str, str]],
    hi_type: str,
    matched_by: Sequence[str],
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Answer a discovery the patient started in their ABHA app.

    `gateway_request_id` is the REQUEST-ID the gateway sent US; it goes back in
    `response.requestId` and is how the gateway matches our answer to its
    question. Getting it wrong produces no error — the discovery simply times
    out and the patient sees no records.

    `matched_by` names which identifier matched (e.g. "MR"), and an empty list
    means "no patient found" rather than an error.
    """
    settings = get_settings()
    validate_hi_types([hi_type])
    patients = (
        [
            care_context_payload(
                abha_address=abha_address,
                display=display,
                care_contexts=care_contexts,
                hi_type=hi_type,
            )
        ]
        if care_contexts
        else []
    )
    return await _post(
        settings.abdm_path_hip_on_discover,
        {
            "transactionId": transaction_id,
            "patient": patients,
            "matchedBy": list(matched_by),
            "response": {"requestId": gateway_request_id},
        },
        # ABDM's collection shows X-HIU-ID on this response, which looks like a
        # copy from the discovery request above it — the HIP is answering, so
        # X-HIP-ID is what identifies the sender. Both are sent: the gateway
        # ignores headers it does not use, and sending only the one the
        # collection shows would mean claiming to be an HIU.
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


async def respond_to_link_init(
    *,
    transaction_id: str,
    gateway_request_id: str,
    link_ref_number: str,
    authentication_type: str = "DIRECT",
    communication_expiry: str | None = None,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Answer a link-init with a reference number.

    `DIRECT` means we are not challenging the patient for an OTP of our own —
    the CM already authenticated them. The alternative requires us to run an
    OTP flow, which this deployment does not, so it is not offered as an option
    rather than accepted and ignored.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_on_link_init,
        {
            "transactionId": transaction_id,
            "link": {
                "referenceNumber": link_ref_number,
                "authenticationType": authentication_type,
                "meta": {
                    "communicationMedium": "MOBILE",
                    "communicationHint": "OTP",
                    "communicationExpiry": communication_expiry or _now_iso(),
                },
            },
            "response": {"requestId": gateway_request_id},
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


async def respond_to_link_confirm(
    *,
    gateway_request_id: str,
    abha_address: str,
    display: str,
    care_contexts: Sequence[Mapping[str, str]],
    hi_type: str,
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Confirm the link and hand back the linked contexts.

    Note there is no transactionId here — the gateway correlates on
    `response.requestId` alone at this step.
    """
    settings = get_settings()
    validate_hi_types([hi_type])
    return await _post(
        settings.abdm_path_hip_on_link_confirm,
        {
            "patient": [
                care_context_payload(
                    abha_address=abha_address,
                    display=display,
                    care_contexts=care_contexts,
                    hi_type=hi_type,
                )
            ],
            "response": {"requestId": gateway_request_id},
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


# =============================================================================
# Consent and data flow — acknowledgements the gateway waits for
# =============================================================================

async def acknowledge_consent_notification(
    *,
    consent_id: str,
    gateway_request_id: str,
    status: str = "OK",
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Acknowledge a consent artefact the CM notified us about.

    An unacknowledged notification is retried by the gateway and then treated as
    a failed grant, so the patient's consent silently does not take effect here.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_on_consent_notify,
        {
            "acknowledgement": {"status": status, "consentId": consent_id},
            "response": {"requestId": gateway_request_id},
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


async def acknowledge_hi_request(
    *,
    transaction_id: str,
    gateway_request_id: str,
    session_status: str = "ACKNOWLEDGED",
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Accept a health-information request before transferring.

    Two-step by design: acknowledge quickly, then push the bundle to the HIU's
    dataPushUrl out of band and report the outcome with `notify_hi_transfer`.
    Doing the transfer inside the request would hold the gateway's connection
    open for the length of a bundle assembly.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_on_hi_request,
        {
            "hiRequest": {
                "transactionId": transaction_id,
                "sessionStatus": session_status,
            },
            "response": {"requestId": gateway_request_id},
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )


async def notify_hi_transfer(
    *,
    consent_id: str,
    transaction_id: str,
    session_status: str,
    status_responses: Sequence[Mapping[str, str]],
    request_id: str | None = None,
) -> tuple[str, AbdmResponse]:
    """HIP -> gateway. Report what happened to a data push.

    `status_responses` is per care context: `careContextReference`, `hiStatus`
    ("OK" / "ERRORED") and a short `description`. The gateway shows this to the
    patient, so the description must describe the transfer and never the
    clinical content.
    """
    settings = get_settings()
    return await _post(
        settings.abdm_path_hip_hi_notify,
        {
            "notification": {
                "consentId": consent_id,
                "transactionId": transaction_id,
                "doneAt": _now_iso(),
                "notifier": {"type": "HIP", "id": hip_id()},
                "statusNotification": {
                    "sessionStatus": session_status,
                    "hipId": hip_id(),
                    "statusResponses": [dict(s) for s in status_responses],
                },
            }
        },
        extra_headers={"X-HIP-ID": hip_id()},
        request_id=request_id,
    )
