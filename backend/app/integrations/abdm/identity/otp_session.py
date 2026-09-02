"""Short-lived state for ABDM's two-legged OTP flows (M1).

WHY THIS EXISTS

Every ABHA identity flow — Aadhaar enrolment, mobile verification, login — is
two calls, not one. The first returns a transaction id; the second presents that
id together with the OTP the patient just received. Something has to hold the
link between those two calls, and where it lives is a privacy decision rather
than a storage one.

WHAT IS DELIBERATELY NOT STORED

The Aadhaar number. Not encrypted, not hashed, not "temporarily". It is sent to
the gateway in the first leg and never persisted here, because the second leg
does not need it — ABDM's transaction id already stands for the identity being
enrolled. Keeping a copy would create Aadhaar-linked personal data at rest for
the sole purpose of avoiding a lookup we do not have to do.

`patients.abha_number` and the encrypted linking token remain the durable
record, written only after a flow completes. This module holds nothing that
outlives an OTP.

WHY REDIS RATHER THAN POSTGRES

An OTP is valid for minutes. A Postgres row would outlive it, would need a
reaper nobody writes, and would put Aadhaar-adjacent state into the backup set —
into the very dumps the production rehearsal copies around. Redis with a TTL
expires the state whether or not any code remembers to.

The trade is honest and worth stating: a Redis restart mid-registration loses
in-flight transactions and the patient must request a new OTP. That is a
recoverable inconvenience. The alternative — durable Aadhaar-linked rows — is
not recoverable once written into a backup.

FACILITY SCOPE IS PART OF THE KEY'S PAYLOAD, NOT ADVISORY

A transaction created at one facility must not be completable from another.
`load()` takes the caller's facility and refuses a mismatch, because an ABDM
transaction id is a bearer-ish value: anyone holding it could otherwise finish
someone else's enrolment and attach an ABHA to a patient record they do not own.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum

from app.common.redis import get_redis

#: ABDM OTPs are short-lived; this is the ceiling on how long our half of the
#: exchange stays valid. Deliberately a little longer than the gateway's own
#: window so the patient sees ABDM's "OTP expired" rather than our "unknown
#: transaction", which is the more actionable message.
OTP_SESSION_TTL_SECONDS = 15 * 60

_KEY_PREFIX = "abdm:otp"


class OtpPurpose(str, Enum):
    """What the OTP is being used for.

    Carried through the exchange and checked on completion so a transaction
    started for one purpose cannot be spent on another — the second leg of an
    enrolment and the second leg of a login are otherwise the same shape.
    """

    #: Create a new ABHA from an Aadhaar number.
    ENROL_BY_AADHAAR = "enrol_by_aadhaar"
    #: Attach/verify a mobile number on a newly created ABHA.
    VERIFY_MOBILE = "verify_mobile"
    #: Authenticate an EXISTING ABHA the patient already holds.
    LOGIN_BY_ABHA = "login_by_abha"


class OtpSessionNotFound(Exception):
    """Expired, already spent, or never existed.

    One exception for all three on purpose: distinguishing them would tell a
    caller whether a transaction id was ever real, which is a probe.
    """


class OtpSessionMismatch(Exception):
    """The session exists but does not belong to this caller or this purpose."""


@dataclass(frozen=True)
class OtpSession:
    """Our half of an in-flight OTP exchange.

    Note what is absent: no Aadhaar number, no mobile number, no OTP. The OTP is
    never seen by us at all — the patient types it and it goes straight back to
    the gateway.
    """

    #: Our id, handed to the client. Not ABDM's — see abdm_txn_id.
    session_id: str
    #: ABDM's transaction id from the first leg. The second leg needs it.
    abdm_txn_id: str
    purpose: OtpPurpose
    facility_id: str
    #: Who started it, so the completion is attributable to the same staff
    #: member — the same rule as created_by everywhere else in this codebase.
    started_by: str
    #: Set for flows attaching an ABHA to an existing patient; None while
    #: enrolling someone who has no record yet.
    patient_id: str | None
    created_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self) | {"purpose": self.purpose.value})

    @classmethod
    def from_json(cls, raw: str) -> OtpSession:
        data = json.loads(raw)
        return cls(**(data | {"purpose": OtpPurpose(data["purpose"])}))


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}:{session_id}"


async def start(
    *,
    abdm_txn_id: str,
    purpose: OtpPurpose,
    facility_id: str,
    started_by: str,
    patient_id: str | None = None,
) -> OtpSession:
    """Record the first leg and return the session the client will quote back.

    The client never sees `abdm_txn_id`. It gets our `session_id` instead, so a
    gateway transaction id is not handed to a browser where it could be replayed
    against ABDM directly.
    """
    session = OtpSession(
        session_id=str(uuid.uuid4()),
        abdm_txn_id=abdm_txn_id,
        purpose=purpose,
        facility_id=str(facility_id),
        started_by=str(started_by),
        patient_id=str(patient_id) if patient_id else None,
        created_at=datetime.now(UTC).isoformat(),
    )
    await get_redis().set(_key(session.session_id), session.to_json(), ex=OTP_SESSION_TTL_SECONDS)
    return session


async def load(session_id: str, *, facility_id: str, purpose: OtpPurpose) -> OtpSession:
    """Fetch a session for its second leg, or refuse.

    Does NOT delete. Verification can legitimately fail on a wrong OTP and the
    patient should get another attempt within the same transaction; ABDM counts
    those attempts itself. `finish()` is what consumes the session.
    """
    raw = await get_redis().get(_key(session_id))
    if raw is None:
        raise OtpSessionNotFound

    session = OtpSession.from_json(raw)
    if session.facility_id != str(facility_id) or session.purpose is not purpose:
        # Same refusal for both, and the same one as "not found" would give a
        # timing-blind caller: a transaction started elsewhere must not be
        # distinguishable from one that never existed.
        raise OtpSessionMismatch
    return session


async def finish(session_id: str) -> None:
    """Consume the session once its flow has completed.

    Called after a SUCCESSFUL verification, never after a failed one. Deleting
    on failure would turn a mistyped digit into "start the whole thing again".
    """
    await get_redis().delete(_key(session_id))
