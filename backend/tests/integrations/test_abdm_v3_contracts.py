"""Official ABDM v3 callback surface and nested wire contracts.

These tests pin the two failures that are otherwise invisible until a sandbox
callback arrives: mounting a correct handler below HealthDoc's ``/api/v1``
prefix, and flattening ABDM's nested camel-case objects into an internal DTO.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.integrations.abdm.contracts_v3 import (
    ConsentOnFetchCallback,
    HealthInformationPush,
    HipHealthInformationCallback,
    ProfileShareCallback,
)
from app.main import app

OFFICIAL_CALLBACK_PATHS = {
    "/api/v3/hip/patient/share",
    "/api/v3/hip/token/on-generate-token",
    "/api/v3/link/on_carecontext",
    "/api/v3/links/context/on-notify",
    "/api/v3/patients/sms/on-notify",
    "/api/v3/hip/patient/care-context/discover",
    "/api/v3/hip/link/care-context/init",
    "/api/v3/hip/link/care-context/confirm",
    "/api/v3/consent/request/hip/notify",
    "/api/v3/hip/health-information/request",
    "/api/v3/hiu/consent/request/on-init",
    "/api/v3/hiu/consent/request/on-status",
    "/api/v3/hiu/consent/request/notify",
    "/api/v3/hiu/consent/on-fetch",
    "/api/v3/hiu/health-information/on-request",
    # Direct HIP -> HIU transfer is nominated in dataPushUrl rather than
    # called by the gateway, but it is part of the same public v3 surface.
    "/api/v3/hiu/health-information/transfer",
}


def test_every_published_v3_callback_is_mounted_at_the_root():
    paths = {route.path for route in app.routes}
    assert OFFICIAL_CALLBACK_PATHS <= paths
    assert (
        not {f"/api/v1{path}" for path in OFFICIAL_CALLBACK_PATHS} & paths
    ), "official callbacks were accidentally mounted below /api/v1"


def test_scan_and_share_parses_the_published_nested_profile():
    callback = ProfileShareCallback.model_validate(
        {
            "intent": "REGISTRATION",
            "metaData": {"hipId": "SBXID_TEST_HIP", "context": "5"},
            "profile": {
                "patient": {
                    "abhaAddress": "patient@sbx",
                    "abhaNumber": "91-1234-5678-9012",
                    "name": "Test Patient",
                    "gender": "M",
                    "yearOfBirth": "1990",
                    "monthOfBirth": "01",
                    "dayOfBirth": "02",
                    "phoneNumber": "9876543210",
                    "identifiers": [{"type": "MOBILE", "value": "******3210"}],
                }
            },
        }
    )
    assert callback.meta_data.hip_id == "SBXID_TEST_HIP"
    assert callback.profile.patient.abha_address == "patient@sbx"


def test_hip_data_request_parses_nested_hi_request_and_key_material():
    expiry = datetime.now(UTC) + timedelta(hours=1)
    callback = HipHealthInformationCallback.model_validate(
        {
            "transactionId": "TX-1",
            "hiRequest": {
                "consent": {"id": "CONSENT-1"},
                "dateRange": {
                    "from": "2026-01-01T00:00:00.000Z",
                    "to": "2026-02-01T00:00:00.000Z",
                },
                "dataPushUrl": "https://hiu.example.org/api/v3/hiu/health-information/transfer",
                "keyMaterial": {
                    "cryptoAlg": "ECDH",
                    "curve": "Curve25519",
                    "dhPublicKey": {
                        "expiry": expiry.isoformat(),
                        "parameters": "Curve25519/32byte random key",
                        "keyValue": "PUBLIC",
                    },
                    "nonce": "NONCE",
                },
            },
        }
    )
    assert callback.hi_request.consent.id == "CONSENT-1"
    assert callback.hi_request.key_material.dh_public_key.key_value == "PUBLIC"


def test_consent_fetch_reads_the_grant_not_the_original_request():
    callback = ConsentOnFetchCallback.model_validate(
        {
            "consent": {
                "status": "GRANTED",
                "consentDetail": {
                    "consentId": "C-1",
                    "patient": {"id": "patient@sbx"},
                    "careContexts": [
                        {
                            "patientReference": "P-1",
                            "careContextReference": "V-1",
                        }
                    ],
                    "hip": {"id": "HIP-1"},
                    "hiu": {"id": "HIU-1"},
                    "hiTypes": ["OPConsultation"],
                    "permission": {
                        "accessMode": "VIEW",
                        "dateRange": {
                            "from": "2026-01-01T00:00:00.000Z",
                            "to": "2026-01-31T00:00:00.000Z",
                        },
                        "dataEraseAt": "2026-02-28T00:00:00.000Z",
                    },
                },
                "signature": "opaque-gateway-artefact-signature",
            },
            "response": {"requestId": "GW-1"},
        }
    )
    detail = callback.consent.consent_detail
    assert detail.hi_types == ["OPConsultation"]
    assert detail.care_contexts[0].care_context_reference == "V-1"


def test_data_push_has_bounded_pages_and_entries():
    key_material = {
        "cryptoAlg": "ECDH",
        "curve": "Curve25519",
        "dhPublicKey": {
            "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "parameters": "Curve25519/32byte random key",
            "keyValue": "PUBLIC",
        },
        "nonce": "NONCE",
    }
    with pytest.raises(ValidationError):
        HealthInformationPush.model_validate(
            {
                "pageNumber": 0,
                "pageCount": 1001,
                "transactionId": "TX-1",
                "entries": [{"content": "x", "media": "application/fhir+json"}],
                "keyMaterial": key_material,
            }
        )
