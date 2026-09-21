"""The OTP transaction store for ABDM identity flows (M1).

These assert the PROPERTIES that do not depend on ABDM's wire format: what is
stored, what is refused, and what expires. The gateway paths and payload field
names are not settled here and are deliberately not guessed at.

Runs against a fake Redis rather than a real one, because every property under
test is about our own logic — key naming, TTL being set at all, scope refusal —
and none of it exercises Redis itself.
"""
from __future__ import annotations

import json
import re
import uuid

import pytest

from app.integrations.abdm.identity import otp_session
from app.integrations.abdm.identity.otp_session import (
    OTP_SESSION_TTL_SECONDS,
    OtpPurpose,
    OtpSessionMismatch,
    OtpSessionNotFound,
)


class _FakeRedis:
    """Minimal stand-in: set/get/delete with the ex= we care about recorded."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.expiries[key] = ex

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.expiries.pop(key, None)


@pytest.fixture
def redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(otp_session, "get_redis", lambda: fake)
    return fake


FACILITY = str(uuid.uuid4())
ACTOR = str(uuid.uuid4())


async def test_the_aadhaar_number_is_never_stored(redis):
    """The point of the module.

    Aadhaar goes to the gateway in the first leg and is not persisted anywhere
    here — the second leg needs ABDM's transaction id, not the identity behind
    it. This asserts on the RAW stored bytes rather than the dataclass, because
    a field added later would be caught here and not by a typed read.
    """
    await otp_session.start(
        abdm_txn_id="abdm-txn-1",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    raw = next(iter(redis.store.values()))
    stored = json.loads(raw)

    # An exact field set, not a substring scan.
    #
    # The first version of this test asserted `"aadhaar" not in raw.lower()`,
    # which FAILS — the purpose value is literally "enrol_by_aadhaar". It would
    # have gone red on a module that stores nothing wrong, and the red would
    # have read as a privacy leak. A test that cries wolf about a leak is worse
    # than no test: the next person's instinct is to weaken the assertion.
    assert set(stored) == {
        "session_id", "abdm_txn_id", "purpose", "facility_id",
        "started_by", "patient_id", "created_at",
        # login_hint is the identifier CATEGORY quoted back as the verify
        # scope ("aadhaar"/"abha-number"), never the identifier; resends is a
        # counter bounding fresh gateway transactions per desk attempt.
        "login_hint", "resends",
        # Enrolment grant identifiers and continuation stage. Never an
        # Aadhaar number, mobile number, OTP, or profile credential.
        "consent_code", "consent_version", "consent_language",
        "consent_granted_at", "stage",
        "selection_token", "account_choices",
    }, "a new field here is a new thing kept about a patient — justify it"

    # And the property the substring check was reaching for, stated so it can
    # only fail for the right reason: no value in the payload looks like an
    # Aadhaar number. Checked over VALUES, so an enum label mentioning Aadhaar
    # is irrelevant while an actual 12-digit identifier is not.
    for field, value in stored.items():
        assert not re.fullmatch(r"\d{12}", str(value or "")), (
            f"{field} holds a 12-digit value — Aadhaar must never be persisted here"
        )


async def test_the_session_always_carries_a_ttl(redis):
    """A session without an expiry is Aadhaar-adjacent state that outlives the
    OTP it belongs to, sitting in memory until something evicts it."""
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-2",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    assert redis.expiries[f"abdm:otp:{session.session_id}"] == OTP_SESSION_TTL_SECONDS


async def test_the_client_never_receives_abdms_transaction_id(redis):
    """Our session_id and ABDM's txn id are different values.

    Handing the gateway's id to a browser would let it be replayed against ABDM
    directly, outside anything this system records.
    """
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-3",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    assert session.session_id != session.abdm_txn_id
    uuid.UUID(session.session_id)  # ours is a UUID; ABDM's format is theirs


async def test_another_facility_cannot_complete_the_flow(redis):
    """An in-flight enrolment is completable only where it started.

    Without this, anyone holding a session id could finish someone else's
    enrolment and attach an ABHA to a patient record at a facility they have no
    relationship with.
    """
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-4",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    with pytest.raises(OtpSessionMismatch):
        await otp_session.load(
            session.session_id,
            facility_id=str(uuid.uuid4()),
            purpose=OtpPurpose.ENROL_BY_AADHAAR,
        )


async def test_a_session_cannot_be_spent_on_a_different_purpose(redis):
    """Enrolment's second leg and login's second leg are the same shape.

    Without the purpose check, an OTP obtained for one could be presented to the
    other, which is a confused-deputy on the patient's identity.
    """
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-5",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    with pytest.raises(OtpSessionMismatch):
        await otp_session.load(
            session.session_id, facility_id=FACILITY, purpose=OtpPurpose.LOGIN_BY_ABHA
        )


async def test_an_unknown_session_is_simply_not_found(redis):
    with pytest.raises(OtpSessionNotFound):
        await otp_session.load(
            str(uuid.uuid4()), facility_id=FACILITY, purpose=OtpPurpose.LOGIN_BY_ABHA
        )


async def test_loading_does_not_consume_the_session(redis):
    """A mistyped OTP must not cost the patient the whole transaction.

    ABDM counts verification attempts itself; deleting on read would turn one
    wrong digit into "request a new OTP and start again".
    """
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-6",
        purpose=OtpPurpose.LOGIN_BY_ABHA,
        facility_id=FACILITY,
        started_by=ACTOR,
    )

    for _ in range(3):
        loaded = await otp_session.load(
            session.session_id, facility_id=FACILITY, purpose=OtpPurpose.LOGIN_BY_ABHA
        )
        assert loaded.abdm_txn_id == "abdm-txn-6"


async def test_finishing_consumes_it(redis):
    """Called only after a SUCCESSFUL verification, so a completed enrolment
    cannot be replayed."""
    session = await otp_session.start(
        abdm_txn_id="abdm-txn-7",
        purpose=OtpPurpose.VERIFY_MOBILE,
        facility_id=FACILITY,
        started_by=ACTOR,
        patient_id=str(uuid.uuid4()),
    )

    await otp_session.finish(session.session_id)

    with pytest.raises(OtpSessionNotFound):
        await otp_session.load(
            session.session_id, facility_id=FACILITY, purpose=OtpPurpose.VERIFY_MOBILE
        )


async def test_the_patient_is_optional_because_enrolment_precedes_the_record(redis):
    """Attaching an ABHA to an existing patient carries patient_id; creating an
    ABHA for someone not yet registered cannot."""
    without = await otp_session.start(
        abdm_txn_id="t1", purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=FACILITY, started_by=ACTOR,
    )
    patient = str(uuid.uuid4())
    with_patient = await otp_session.start(
        abdm_txn_id="t2", purpose=OtpPurpose.VERIFY_MOBILE,
        facility_id=FACILITY, started_by=ACTOR, patient_id=patient,
    )

    assert without.patient_id is None
    assert with_patient.patient_id == patient
