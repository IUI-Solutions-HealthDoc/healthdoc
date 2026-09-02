"""The outbound M2/M3 calls — the half that did not exist until now.

Before this, `abdm_path_hip_*` and `abdm_path_hiu_*` were referenced nowhere
outside config.py: the package could receive and could not speak. Nothing in
the suite noticed, because there is no test that fails when a module simply is
not called.

So these tests assert the WIRE, not the happy path:

  * the exact path each function posts to, since the ten previous values were
    all 404s and only a settings lookup stands between right and wrong;
  * the identifying header, because a HIP call sent without X-HIP-ID is
    anonymous and one sent with X-HIU-ID claims to be somebody else;
  * the payload shape against ABDM's official v3 collection, field by field;
  * that identity placeholders are refused rather than sent as "change-me".

NO CREDENTIALS AND NO NETWORK. The client is stubbed throughout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.common.config import Settings
from app.integrations.abdm.client import AbdmResponse
from app.integrations.abdm.hip import gateway as hip_gw
from app.integrations.abdm.hiu import gateway as hiu_gw

pytestmark = pytest.mark.asyncio

FROM = datetime(2026, 1, 1, tzinfo=UTC)
TO = datetime(2026, 6, 1, tzinfo=UTC)


class _StubClient:
    """Records every call. Never touches a network."""

    def __init__(self, body=None, status=202):
        self.calls: list[dict] = []
        self._body = body if body is not None else {}
        self._status = status

    async def request(self, method, path, *, json=None, extra_headers=None, request_id=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json": json,
                "headers": dict(extra_headers or {}),
                "request_id": request_id,
            }
        )
        return AbdmResponse(self._status, self._body, "stub-request-id")

    @property
    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture
def stub(monkeypatch):
    client = _StubClient()
    monkeypatch.setattr(hip_gw, "get_abdm_client", lambda: client)
    monkeypatch.setattr(hiu_gw, "get_abdm_client", lambda: client)

    settings = Settings(
        _env_file=None,
        abdm_hip_id="SBXID_TEST_HIP",
        abdm_hiu_id="SBXID_TEST_HIU",
        abdm_hiu_callback_base_url="https://abdm.example.org",
    )
    monkeypatch.setattr(hip_gw, "get_settings", lambda: settings)
    monkeypatch.setattr(hiu_gw, "get_settings", lambda: settings)
    return client


# =============================================================================
# Identity — refuse rather than send a placeholder
# =============================================================================


@pytest.mark.parametrize("value", ["change-me", ""])
async def test_hip_calls_refuse_an_unset_identity(monkeypatch, stub, value):
    """ "change-me" as a HIP id either fails confusingly or hits someone else's
    registration. Neither is acceptable, so it never reaches the wire."""
    monkeypatch.setattr(
        hip_gw,
        "get_settings",
        lambda: Settings(_env_file=None, abdm_hip_id=value),
    )
    with pytest.raises(hip_gw.HipIdentityNotConfigured):
        await hip_gw.notify_care_context(
            abha_address="x@sbx", care_context_reference="C1", hi_types=["Prescription"]
        )
    assert stub.calls == [], "a request was built with an unconfigured identity"


@pytest.mark.parametrize("value", ["change-me", ""])
async def test_hiu_calls_refuse_an_unset_identity(monkeypatch, stub, value):
    monkeypatch.setattr(
        hiu_gw,
        "get_settings",
        lambda: Settings(_env_file=None, abdm_hiu_id=value),
    )
    with pytest.raises(hiu_gw.HiuIdentityNotConfigured):
        await hiu_gw.fetch_consent_artefact(consent_id="c-1")
    assert stub.calls == []


async def test_an_hi_request_refuses_an_unset_push_url(monkeypatch, stub):
    """A request with an unreachable push address is the worst failure mode
    here: the gateway accepts it, a HIP encrypts a real patient's records, and
    the delivery fails somewhere we cannot see."""
    monkeypatch.setattr(
        hiu_gw,
        "get_settings",
        lambda: Settings(_env_file=None, abdm_hiu_id="X", abdm_hiu_callback_base_url="change-me"),
    )
    with pytest.raises(hiu_gw.DataPushUrlNotConfigured):
        await hiu_gw.request_health_information(
            consent_id="c-1",
            date_from=FROM,
            date_to=TO,
            dh_public_key="k",
            key_expiry=TO,
            nonce="n",
        )
    assert stub.calls == []


# =============================================================================
# HIP — paths, headers, shapes
# =============================================================================


async def test_link_care_contexts_sends_the_link_token_header(stub):
    """Without X-LINK-TOKEN the gateway answers 401, which reads as a
    credentials problem and sends you to the wrong place entirely."""
    await hip_gw.link_care_contexts(
        abha_address="ram@sbx",
        link_token="LT-1",
        display="Blood Test",
        care_contexts=[{"referenceNumber": "V-1", "display": "Blood Test"}],
        hi_type="Prescription",
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/hip/v3/link/carecontext"
    assert call["headers"] == {"X-HIP-ID": "SBXID_TEST_HIP", "X-LINK-TOKEN": "LT-1"}
    assert call["json"]["abhaAddress"] == "ram@sbx"
    patient = call["json"]["patient"][0]
    assert patient["referenceNumber"] == "ram@sbx"
    assert patient["careContexts"] == [{"referenceNumber": "V-1", "display": "Blood Test"}]
    assert patient["count"] == 1


async def test_notify_care_context_shape(stub):
    await hip_gw.notify_care_context(
        abha_address="ram@sbx",
        care_context_reference="V-1",
        hi_types=["DiagnosticReport", "DischargeSummary"],
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/hip/v3/link/context/notify"
    n = call["json"]["notification"]
    assert n["patient"] == {"id": "ram@sbx"}
    assert n["careContext"] == {"patientReference": "ram@sbx", "careContextReference": "V-1"}
    assert n["hip"] == {"id": "SBXID_TEST_HIP"}
    assert n["hiTypes"] == ["DiagnosticReport", "DischargeSummary"]


async def test_on_discover_echoes_the_gateways_request_id(stub):
    """`response.requestId` is how the gateway matches our answer to its
    question. Get it wrong and there is no error — the discovery times out and
    the patient is shown no records."""
    await hip_gw.respond_to_discovery(
        transaction_id="T-1",
        gateway_request_id="GW-REQ-9",
        abha_address="ram@sbx",
        display="OPD",
        care_contexts=[{"referenceNumber": "V-1", "display": "OPD"}],
        hi_type="OPConsultation",
        matched_by=["MR"],
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover"
    assert call["json"]["response"] == {"requestId": "GW-REQ-9"}
    assert call["json"]["transactionId"] == "T-1"
    assert call["json"]["matchedBy"] == ["MR"]


async def test_on_discover_with_no_matches_sends_an_empty_patient_list(stub):
    """ "We found nobody" is a valid discovery answer and is not an error.
    Sending a patient element with zero care contexts would claim a match."""
    await hip_gw.respond_to_discovery(
        transaction_id="T-1",
        gateway_request_id="GW-1",
        abha_address="ram@sbx",
        display="OPD",
        care_contexts=[],
        hi_type="OPConsultation",
        matched_by=[],
    )
    assert stub.last["json"]["patient"] == []


async def test_link_init_declares_mediated_mobile_otp(stub):
    await hip_gw.respond_to_link_init(
        transaction_id="T-1",
        gateway_request_id="GW-1",
        link_ref_number="LINK-1",
        communication_hint="******3210",
        communication_expiry="2026-06-01T00:10:00.000Z",
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/user-initiated-linking/v3/link/care-context/on-init"
    assert call["json"]["link"] == {
        "referenceNumber": "LINK-1",
        "authenticationType": "MEDIATE",
        "meta": {
            "communicationMedium": "MOBILE",
            "communicationHint": "******3210",
            "communicationExpiry": "2026-06-01T00:10:00.000Z",
        },
    }


async def test_invalid_link_otp_is_returned_as_an_error_not_a_patient(stub):
    await hip_gw.respond_to_link_confirm_error(
        gateway_request_id="GW-1",
        code="ABDM-1035",
        message="Incorrect OTP",
    )
    assert stub.last["json"] == {
        "error": {"code": "ABDM-1035", "message": "Incorrect OTP"},
        "response": {"requestId": "GW-1"},
    }


async def test_hip_acknowledgement_is_an_object_not_a_list(stub):
    """The HIP takes an object and the HIU takes a list. ABDM's asymmetry, and
    exactly the shape that produces a validation error naming a field that
    looks correct."""
    await hip_gw.acknowledge_consent_notification(consent_id="C-1", gateway_request_id="GW-1")
    ack = stub.last["json"]["acknowledgement"]
    assert isinstance(ack, dict)
    assert ack == {"status": "OK", "consentId": "C-1"}
    assert stub.last["path"] == "/api/hiecm/consent/v3/request/hip/on-notify"


async def test_profile_share_ack_uses_duration_not_timestamp(stub):
    await hip_gw.acknowledge_profile_share(
        gateway_request_id="GW-1",
        abha_address="ram@sbx",
        context="5",
        token_number="15",
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/patient-share/v3/on-share"
    assert call["headers"] == {"X-HIP-ID": "SBXID_TEST_HIP"}
    assert call["json"]["acknowledgement"]["profile"] == {
        "context": "5",
        "tokenNumber": "15",
        "expiry": "1800",
    }


async def test_hi_transfer_notification_identifies_us_as_the_hip(stub):
    await hip_gw.notify_hi_transfer(
        consent_id="C-1",
        transaction_id="T-1",
        session_status="TRANSFERRED",
        status_responses=[{"careContextReference": "V-1", "hiStatus": "OK", "description": "sent"}],
    )
    n = stub.last["json"]["notification"]
    assert n["notifier"] == {"type": "HIP", "id": "SBXID_TEST_HIP"}
    assert n["statusNotification"]["hipId"] == "SBXID_TEST_HIP"
    assert stub.last["path"] == "/api/hiecm/data-flow/v3/health-information/notify"


# =============================================================================
# HIU — paths, headers, shapes
# =============================================================================


async def test_consent_request_shape(stub):
    await hiu_gw.request_consent(
        abha_address="ram@sbx",
        hi_types=["Prescription"],
        date_from=FROM,
        date_to=TO,
        expiry=TO + timedelta(days=30),
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/consent/v3/request/init"
    assert call["headers"] == {"X-HIU-ID": "SBXID_TEST_HIU"}
    consent = call["json"]["consent"]
    assert consent["hiu"] == {"id": "SBXID_TEST_HIU"}
    # ABDM's own example sends an explicit null for "any HIP".
    assert consent["hip"] is None
    assert consent["patient"] == {"id": "ram@sbx"}
    assert consent["purpose"]["code"] == "CAREMGT"
    assert consent["permission"]["accessMode"] == "VIEW"
    assert consent["permission"]["dateRange"]["from"] == "2026-01-01T00:00:00.000Z"


async def test_hiu_acknowledgement_is_a_list_not_an_object(stub):
    await hiu_gw.acknowledge_consent_notification(consent_id="C-1", gateway_request_id="GW-1")
    ack = stub.last["json"]["acknowledgement"]
    assert isinstance(ack, list)
    assert ack == [{"status": "OK", "consentId": "C-1"}]
    assert stub.last["headers"] == {"X-HIU-ID": "SBXID_TEST_HIU"}


async def test_health_information_request_carries_key_material_and_push_url(stub):
    await hiu_gw.request_health_information(
        consent_id="C-1",
        date_from=FROM,
        date_to=TO,
        dh_public_key="PUBKEY",
        key_expiry=TO,
        nonce="NONCE-1",
    )
    call = stub.last
    assert call["path"] == "/api/hiecm/data-flow/v3/health-information/request"
    assert call["headers"] == {"X-HIU-ID": "SBXID_TEST_HIU"}
    hi = call["json"]["hiRequest"]
    assert hi["consent"] == {"id": "C-1"}
    assert hi["dataPushUrl"] == ("https://abdm.example.org/api/v3/hiu/health-information/transfer")
    km = hi["keyMaterial"]
    assert km["cryptoAlg"] == "ECDH"
    assert km["curve"] == "Curve25519"
    assert km["dhPublicKey"]["keyValue"] == "PUBKEY"
    assert km["nonce"] == "NONCE-1"


async def test_fetch_artefact_sends_the_hiu_header(stub):
    await hiu_gw.fetch_consent_artefact(consent_id="C-1")
    assert stub.last["path"] == "/api/hiecm/consent/v3/fetch"
    assert stub.last["headers"] == {"X-HIU-ID": "SBXID_TEST_HIU"}
    assert stub.last["json"] == {"consentId": "C-1"}


async def test_hiu_receipt_notification_identifies_us_as_the_hiu(stub):
    """Same endpoint as the HIP notification — `notifier.type` is the only
    thing distinguishing the two sides."""
    await hiu_gw.notify_hi_receipt(
        consent_id="C-1",
        transaction_id="T-1",
        session_status="RECEIVED",
        hip_id="OTHER_HIP",
        status_responses=[{"careContextReference": "V-1", "hiStatus": "OK", "description": "ok"}],
    )
    n = stub.last["json"]["notification"]
    assert n["notifier"] == {"type": "HIU", "id": "SBXID_TEST_HIU"}
    # hipId names the SENDER, which is not us.
    assert n["statusNotification"]["hipId"] == "OTHER_HIP"


# =============================================================================
# Shared validation
# =============================================================================


async def test_an_unknown_hi_type_is_refused_before_the_wire(stub):
    """ABDM rejects these with a message that names the field and not the
    allowed values, so the list is checked where it can be read."""
    with pytest.raises(ValueError, match="Unknown ABDM health-information type"):
        await hip_gw.notify_care_context(
            abha_address="ram@sbx",
            care_context_reference="V-1",
            hi_types=["Prescription", "NotARealType"],
        )
    assert stub.calls == []


async def test_an_empty_hi_type_list_is_refused(stub):
    with pytest.raises(ValueError, match="At least one"):
        await hip_gw.notify_care_context(
            abha_address="ram@sbx", care_context_reference="V-1", hi_types=[]
        )
    assert stub.calls == []


async def test_a_backwards_date_range_is_refused(stub):
    with pytest.raises(ValueError, match="before"):
        await hiu_gw.request_consent(
            abha_address="ram@sbx",
            hi_types=["Prescription"],
            date_from=TO,
            date_to=FROM,
            expiry=TO,
        )
    assert stub.calls == []


async def test_timestamps_use_a_literal_z_not_an_offset(stub):
    """`datetime.isoformat()` produces `+00:00`, which some ABDM endpoints
    reject and others silently accept — the inconsistent kind of bug."""
    await hiu_gw.request_consent(
        abha_address="ram@sbx",
        hi_types=["Prescription"],
        date_from=FROM,
        date_to=TO,
        expiry=TO,
    )
    rng = stub.last["json"]["consent"]["permission"]["dateRange"]
    assert rng["from"].endswith("Z") and "+00:00" not in rng["from"]
    assert rng["to"].endswith("Z")


async def test_a_naive_datetime_is_treated_as_utc_not_local(stub):
    """A naive datetime reaching the wire as local time would shift a consent
    window by hours, silently widening or narrowing what was permitted."""
    await hiu_gw.request_consent(
        abha_address="ram@sbx",
        hi_types=["Prescription"],
        date_from=datetime(2026, 1, 1),
        date_to=datetime(2026, 6, 1),
        expiry=datetime(2026, 6, 1),
    )
    assert stub.last["json"]["consent"]["permission"]["dateRange"]["from"] == (
        "2026-01-01T00:00:00.000Z"
    )


async def test_the_request_id_is_returned_for_correlation(stub):
    """Every one of these flows answers on a callback minutes later carrying
    `response.requestId`. Without the id we sent there is nothing to match."""
    request_id, _ = await hip_gw.acknowledge_hi_request(
        transaction_id="T-1", gateway_request_id="GW-1"
    )
    assert request_id == stub.last["request_id"]
    assert request_id


async def test_a_supplied_request_id_is_reused_for_retries(stub):
    """ABDM treats REQUEST-ID as the idempotency key on several endpoints, so a
    genuine retry has to carry the original or it books twice."""
    await hip_gw.acknowledge_hi_request(
        transaction_id="T-1", gateway_request_id="GW-1", request_id="FIXED-ID"
    )
    assert stub.last["request_id"] == "FIXED-ID"
