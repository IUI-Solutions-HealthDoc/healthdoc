"""ABDM M1 — ABHA enrolment and login.

FULLY MOCKED. No ABDM credentials, no network, no sandbox. CI must never hold
ABDM credentials and these tests must stay that way; the RSA key below is
generated per run and exists only in memory.

WHAT THESE ASSERT

Not "the happy path returns a number" — that is the least interesting property
and the easiest to fake. The assertions here are about the things that would be
findings:

  - the Aadhaar number is ENCRYPTED before it goes anywhere, and never appears
    in a request body, a session, or a log;
  - a transaction started at one facility cannot be completed from another;
  - a session opened for enrolment cannot be spent on a login;
  - a response that carries no ABHA number is a failure, not a silent success
    that writes an unverified identity onto a patient record.
"""
from __future__ import annotations

import base64
import json
import logging

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.integrations.abdm.client import AbdmRejected, AbdmResponse
from app.integrations.abdm.identity import crypto, otp_session, service
from app.integrations.abdm.identity.otp_session import (
    OtpPurpose,
    OtpSessionMismatch,
    OtpSessionNotFound,
)

pytestmark = pytest.mark.asyncio

AADHAAR = "999988887777"
FACILITY_A = "11111111-1111-1111-1111-111111111111"
FACILITY_B = "22222222-2222-2222-2222-222222222222"
STAFF = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _abdm_public_key(monkeypatch, rsa_key):
    pem = rsa_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    class _S:
        abdm_public_key_pem = pem
        abdm_abha_base_url = "https://abha.test/abha/api"
        abdm_path_enrol_request_otp = "/v3/enrollment/request/otp"
        abdm_path_enrol_by_aadhaar = "/v3/enrollment/enrol/byAadhaar"
        abdm_path_login_request_otp = "/v3/profile/login/request/otp"
        abdm_path_login_verify = "/v3/profile/login/verify"

    monkeypatch.setattr(crypto, "get_settings", lambda: _S())
    monkeypatch.setattr(service, "get_settings", lambda: _S())
    return _S


class _FakeRedis:
    """In-memory stand-in. TTLs are accepted and ignored — expiry is Redis's
    job and not what these tests are about."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(otp_session, "get_redis", lambda: redis)
    return redis


class _Gateway:
    """Records what was POSTed so the tests can inspect the wire payload."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def request(self, method, path, *, json=None, **kw):
        self.calls.append((path, json))
        body = self._responses.pop(0) if self._responses else {}
        return AbdmResponse(200, body, "req-id")

    @property
    def last_body(self) -> dict:
        return self.calls[-1][1]


def _gateway(monkeypatch, responses):
    gw = _Gateway(responses)
    monkeypatch.setattr(service, "get_abdm_client", lambda: gw)
    return gw


def _decrypt(rsa_key, b64: str) -> str:
    # /abha/api/v3/profile/public/certificate, observed 2026-09-06:
    # encryptionAlgorithm = RSA/ECB/OAEPWithSHA-1AndMGF1Padding.
    return rsa_key.decrypt(base64.b64decode(b64), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None,
    )).decode()


async def test_gateway_rejection_logs_only_safe_metadata(monkeypatch, caplog):
    class RejectingGateway:
        async def request(self, *args, **kwargs):
            raise AbdmRejected(400, {
                "code": "ABDM-1042",
                "loginId": "private-identifier",
                "message": "private-identifier secret-token",
                "errors": [{"field": "otpValue", "message": "private-otp"},
                           {"code": "private-identifier", "field": "secret-token"}],
            }, "11111111-1111-4111-8111-111111111111")

    monkeypatch.setattr(service, "get_abdm_client", lambda: RejectingGateway())
    with caplog.at_level(logging.WARNING), pytest.raises(AbdmRejected):
        await service.request_login_otp(
            abha_number="91111122223333", facility_id=FACILITY_A, started_by=STAFF,
        )
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "ABDM-1042" in message
    assert "loginId" in message and "otpValue" in message
    assert "11111111-1111-4111-8111-111111111111" in message
    for private in ("private-identifier", "secret-token", "private-otp", "91111122223333"):
        assert private not in message


@pytest.mark.parametrize("number", ["91111122223333", "91-1111-2222-3333", " 91-1111-2222-3333 "])
async def test_login_encrypts_the_hyphenated_abha_number(monkeypatch, rsa_key, number):
    gw = _gateway(monkeypatch, [{"txnId": "synthetic-login-transaction"}])
    await service.request_login_otp(
        abha_number=number, facility_id=FACILITY_A, started_by=STAFF,
    )
    assert gw.calls[0][0] == "https://abha.test/abha/api/v3/profile/login/request/otp"
    assert set(gw.last_body) == {"scope", "loginHint", "otpSystem", "loginId"}
    assert gw.last_body["scope"] == ["abha-login", "mobile-verify"]
    assert gw.last_body["loginHint"] == "abha-number"
    assert gw.last_body["otpSystem"] == "abdm"
    assert _decrypt(rsa_key, gw.last_body["loginId"]) == "91-1111-2222-3333"
    assert "91111122223333" not in json.dumps(gw.last_body)
    assert "91-1111-2222-3333" not in json.dumps(gw.last_body)


# ------------------------------------------------- the Aadhaar never travels raw

async def test_the_aadhaar_number_is_encrypted_on_the_wire(monkeypatch, rsa_key):
    gw = _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}])

    await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    raw = json.dumps(gw.last_body)
    assert AADHAAR not in raw, "the Aadhaar number was sent in the clear"
    # And it is genuinely OUR ciphertext, not some other field that happens to
    # be absent — decrypting it must give the number back.
    assert _decrypt(rsa_key, gw.last_body["loginId"]) == AADHAAR


#: Everything an OTP session is allowed to persist. Deliberately exhaustive.
#:
#: The first version of this test searched the stored blob for any twelve-digit
#: run, reasoning that Aadhaar is twelve digits. It failed on FACILITY_A —
#: "11111111-1111-1111-1111-111111111111" contains one. The regex was matching
#: the shape of the data rather than its meaning, which is the same mistake as
#: asserting on log prose: coincidence and violation look identical.
#:
#: An exact field set is stronger anyway. A regex asks "does anything look like
#: an Aadhaar"; this asks "is there a field here nobody agreed to store", which
#: catches a leak under ANY name, in any format, including a hashed or
#: truncated one that no pattern would match.
_ALLOWED_SESSION_FIELDS = {
    "session_id",
    "abdm_txn_id",
    "purpose",
    "facility_id",
    "started_by",
    "patient_id",
    "created_at",
}


async def test_the_otp_session_stores_no_field_nobody_agreed_to(monkeypatch, fake_redis):
    _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}])

    await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    assert fake_redis.store, "nothing was written — the test is not exercising storage"
    for raw in fake_redis.store.values():
        stored = json.loads(raw)
        unexpected = set(stored) - _ALLOWED_SESSION_FIELDS
        assert not unexpected, (
            f"the OTP session gained field(s) {sorted(unexpected)}. If one of them "
            f"carries identity material, it now outlives the request in Redis."
        )
        # And the number itself, by value, wherever it might have been put.
        assert AADHAAR not in raw, "the Aadhaar number was persisted to Redis"


async def test_the_aadhaar_number_is_never_logged(monkeypatch, caplog):
    _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}])

    with caplog.at_level(logging.DEBUG):
        await service.request_aadhaar_otp(
            aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
        )

    assert AADHAAR not in " ".join(r.getMessage() for r in caplog.records)


async def test_the_otp_is_encrypted_too(monkeypatch, rsa_key):
    gw = _gateway(monkeypatch, [
        {"txnId": "abdm-txn-1"},
        {"ABHAProfile": {"ABHANumber": "91-1234-5678-9012"}, "token": "tok"},
    ])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )
    await service.enrol_by_aadhaar_otp(
        session_id=requested.session_id, otp="123456", mobile=None, facility_id=FACILITY_A
    )

    otp_field = gw.last_body["authData"]["otp"]["otpValue"]
    assert "123456" not in json.dumps(gw.last_body)
    assert _decrypt(rsa_key, otp_field) == "123456"


async def test_enrolment_mobile_is_national_digits_while_otp_is_encrypted(monkeypatch, rsa_key):
    """Supplied M1 byAadhaar 200 sample: mobile is not RSA ciphertext."""
    gw = _gateway(monkeypatch, [
        {"txnId": "abdm-txn-1"},
        {"ABHAProfile": {"ABHANumber": "91-1234-5678-9012"}, "token": "tok"},
    ])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF,
    )
    await service.enrol_by_aadhaar_otp(
        session_id=requested.session_id, otp="123456", mobile="9876543210",
        facility_id=FACILITY_A,
    )
    otp_payload = gw.last_body["authData"]["otp"]
    assert otp_payload["mobile"] == "9876543210"
    assert _decrypt(rsa_key, otp_payload["otpValue"]) == "123456"
    assert "timeStamp" not in otp_payload  # Optional, not an invented null value.


# ------------------------------------------------------------ scope and purpose

async def test_a_transaction_cannot_be_completed_from_another_facility(monkeypatch):
    _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    with pytest.raises(OtpSessionMismatch):
        await service.enrol_by_aadhaar_otp(
            session_id=requested.session_id, otp="123456", mobile=None,
            facility_id=FACILITY_B,
        )


async def test_an_enrolment_session_cannot_be_spent_on_a_login(monkeypatch):
    _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    with pytest.raises(OtpSessionMismatch):
        await service.verify_login_otp(
            session_id=requested.session_id, otp="123456", facility_id=FACILITY_A
        )


async def test_abdm_transaction_id_is_not_returned_to_the_caller(monkeypatch):
    """The client gets OUR session id. Handing it ABDM's transaction id would
    let a browser drive the second leg against ABDM directly."""
    _gateway(monkeypatch, [{"txnId": "abdm-txn-SECRET"}])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )
    assert requested.session_id != "abdm-txn-SECRET"
    assert "abdm-txn-SECRET" not in requested.session_id


# ------------------------------------------------------- refusing bad responses

async def test_a_response_with_no_transaction_id_is_a_failure(monkeypatch):
    """Building a session on a misread response would strand the second leg."""
    _gateway(monkeypatch, [{"message": "OTP sent"}])

    with pytest.raises(service.AbdmIdentityError) as caught:
        await service.request_aadhaar_otp(
            aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
        )
    assert caught.value.code == "abdm_bad_response"


async def test_an_enrolment_with_no_abha_number_is_not_a_success(monkeypatch):
    """The dangerous shape: a 200 that looks fine and carries no identity.

    Treating it as success would write a verified identity onto a patient
    record on the strength of an empty answer.
    """
    _gateway(monkeypatch, [
        {"txnId": "abdm-txn-1"},
        {"ABHAProfile": {}},
    ])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    with pytest.raises(service.AbdmIdentityError) as caught:
        await service.enrol_by_aadhaar_otp(
            session_id=requested.session_id, otp="123456", mobile=None,
            facility_id=FACILITY_A,
        )
    assert caught.value.code == "abdm_no_abha_returned"


async def test_a_failed_verification_leaves_the_session_alive(monkeypatch, fake_redis):
    """A mistyped digit must not mean starting the whole exchange again — ABDM
    counts attempts within its own transaction."""
    _gateway(monkeypatch, [{"txnId": "abdm-txn-1"}, {"ABHAProfile": {}}])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )

    with pytest.raises(service.AbdmIdentityError):
        await service.enrol_by_aadhaar_otp(
            session_id=requested.session_id, otp="000000", mobile=None,
            facility_id=FACILITY_A,
        )

    session = await otp_session.load(
        requested.session_id, facility_id=FACILITY_A, purpose=OtpPurpose.ENROL_BY_AADHAAR
    )
    assert session.abdm_txn_id == "abdm-txn-1"


async def test_a_successful_enrolment_consumes_the_session(monkeypatch):
    _gateway(monkeypatch, [
        {"txnId": "abdm-txn-1"},
        {"ABHAProfile": {"ABHANumber": "91-1234-5678-9012", "name": "Test Patient"}},
    ])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )
    issued = await service.enrol_by_aadhaar_otp(
        session_id=requested.session_id, otp="123456", mobile=None, facility_id=FACILITY_A
    )
    assert issued.abha_number == "91-1234-5678-9012"

    with pytest.raises(OtpSessionNotFound):
        await otp_session.load(
            requested.session_id, facility_id=FACILITY_A,
            purpose=OtpPurpose.ENROL_BY_AADHAAR,
        )


# --------------------------------------------------------------- field aliases

@pytest.mark.parametrize("txn_field", ["txnId", "transactionId", "txnID"])
async def test_transaction_id_is_read_under_any_of_abdms_names(monkeypatch, txn_field):
    """ABDM has used all three across versions. Accepting each is cheaper than
    a flow that dies on a rename — and cheaper than picking one and being
    wrong half the time."""
    _gateway(monkeypatch, [{txn_field: "abdm-txn-1"}])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )
    assert requested.session_id


@pytest.mark.parametrize("profile_key", ["ABHAProfile", "abhaProfile"])
@pytest.mark.parametrize("number_key", ["ABHANumber", "abhaNumber"])
async def test_profile_is_read_under_either_casing(monkeypatch, profile_key, number_key):
    _gateway(monkeypatch, [
        {"txnId": "t"},
        {profile_key: {number_key: "91-1111-2222-3333"}},
    ])
    requested = await service.request_aadhaar_otp(
        aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF
    )
    issued = await service.enrol_by_aadhaar_otp(
        session_id=requested.session_id, otp="123456", mobile=None, facility_id=FACILITY_A
    )
    assert issued.abha_number == "91-1111-2222-3333"


# ------------------------------------------------------------- key not configured

async def test_no_public_key_means_refusal_not_plaintext(monkeypatch):
    """Every available degradation here means sending an Aadhaar number in the
    clear, so there is no degradation — it raises."""
    class _S:
        abdm_public_key_pem = None

    monkeypatch.setattr(crypto, "get_settings", lambda: _S())

    with pytest.raises(crypto.AbdmPublicKeyMissing):
        crypto.encrypt_for_abdm(AADHAAR)


async def test_the_placeholder_is_treated_as_absent(monkeypatch):
    """`change-me` is what ships in .env.example; it must not be used as a key."""
    class _S:
        abdm_public_key_pem = "change-me"

    monkeypatch.setattr(crypto, "get_settings", lambda: _S())

    with pytest.raises(crypto.AbdmPublicKeyMissing):
        crypto.encrypt_for_abdm(AADHAAR)


async def test_v3_login_uses_the_verified_account_not_enrolment_profile(monkeypatch):
    """Shape from supplied M1 collection; identities/tokens are synthetic."""
    _gateway(monkeypatch, [
        {"txnId": "login-test"},
        {"authResult": "success", "token": "synthetic-account-token", "accounts": [
            {"ABHANumber": "91-1111-2222-3333", "preferredAbhaAddress": "test@sbx",
             "name": "Synthetic Patient", "status": "ACTIVE"},
        ]},
    ])
    request = await service.request_login_otp(
        abha_number="91-1111-2222-3333", facility_id=FACILITY_A, started_by=STAFF,
    )
    result = await service.verify_login_otp(
        session_id=request.session_id, otp="123456", facility_id=FACILITY_A,
    )
    assert result.abha_number == "91-1111-2222-3333"
    assert result.abha_address == "test@sbx"
    assert result.name == "Synthetic Patient"


@pytest.mark.parametrize("auth_result,accounts", [
    ("failed", [{"ABHANumber": "91-1111-2222-3333", "status": "ACTIVE"}]),
    (None, [{"ABHANumber": "91-1111-2222-3333", "status": "ACTIVE"}]),
    ("success", []),
    ("success", [{"ABHANumber": "91-1111-2222-3333", "status": "DEACTIVATED"}]),
    ("success", [{"ABHANumber": "91-1111-2222-3333", "status": "ACTIVE"}] * 2),
])
async def test_login_never_guesses_an_account_or_accepts_failed_auth(monkeypatch, auth_result, accounts):
    _gateway(monkeypatch, [{"txnId": "login-test"},
        {"authResult": auth_result, "token": "synthetic", "accounts": accounts}])
    request = await service.request_login_otp(
        abha_number="91-1111-2222-3333", facility_id=FACILITY_A, started_by=STAFF,
    )
    with pytest.raises(service.AbdmIdentityError):
        await service.verify_login_otp(
            session_id=request.session_id, otp="123456", facility_id=FACILITY_A,
        )
    await otp_session.load(request.session_id, facility_id=FACILITY_A, purpose=OtpPurpose.LOGIN_BY_ABHA)


async def test_enrolment_address_list_becomes_a_scalar(monkeypatch):
    _gateway(monkeypatch, [{"txnId": "enrol-test"}, {"tokens": {"token": "synthetic"},
        "ABHAProfile": {"ABHANumber": "91-1111-2222-3333", "phrAddress": ["test@sbx"],
                        "firstName": "Synthetic", "lastName": "Patient"}}])
    request = await service.request_aadhaar_otp(aadhaar=AADHAAR, facility_id=FACILITY_A, started_by=STAFF)
    result = await service.enrol_by_aadhaar_otp(
        session_id=request.session_id, otp="123456", mobile=None, facility_id=FACILITY_A,
    )
    assert result.abha_address == "test@sbx"
    assert result.name == "Synthetic Patient"
