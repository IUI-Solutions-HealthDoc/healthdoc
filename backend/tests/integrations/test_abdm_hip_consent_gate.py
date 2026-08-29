"""The HIP gate: no records leave without a stored, live, matching artefact.

`authorise_hi_request` is the single function that decides whether a patient's
records leave the building, so it gets the most tests in this module. Each one
is a refusal path with a name, because "why did you release this" is the
question, and a compound boolean cannot answer it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.integrations.abdm.hip import service
from app.integrations.abdm.hip.models import AbdmHipConsentArtefact

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
FACILITY = uuid.uuid4()
OTHER_FACILITY = uuid.uuid4()


async def _facility(db, facility_id, code):
    await db.execute(
        text(
            # is_active is NOT NULL with a PYTHON-side default, which a raw
            # INSERT never applies — spelled out rather than relying on it.
            "INSERT INTO facilities (id, code, name, state_code, timezone, is_active) "
            "VALUES (:id, :code, 'Test', 'DL', 'Asia/Kolkata', 1)"
        ),
        {"id": str(facility_id), "code": code},
    )


async def _artefact(db, *, facility_id=FACILITY, artefact_id="ART-1", status="granted",
                    hi_types=None, frm=None, to=None, expires=None):
    row = AbdmHipConsentArtefact(
        facility_id=facility_id,
        consent_artefact_id=artefact_id,
        abha_address="someone@sbx",
        status=status,
        hi_types=hi_types if hi_types is not None else ["OPConsultation", "Prescription"],
        date_range_from=frm or NOW - timedelta(days=30),
        date_range_to=to or NOW + timedelta(days=30),
        expires_at=expires if expires is not None else NOW + timedelta(days=60),
        raw_artefact={"id": artefact_id},
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def hip_db(db):
    await _facility(db, FACILITY, "HIPF1")
    await _facility(db, OTHER_FACILITY, "HIPF2")
    return db


async def _authorise(db, **kwargs):
    call = {
        "facility_id": FACILITY,
        "consent_artefact_id": "ART-1",
        "requested_hi_types": ["OPConsultation"],
        "requested_from": NOW - timedelta(days=1),
        "requested_to": NOW,
        "now": NOW,
        **kwargs,
    }
    return await service.authorise_hi_request(db, **call)


async def test_a_valid_artefact_authorises_and_narrows_to_what_was_granted(hip_db):
    await _artefact(hip_db)
    result = await _authorise(hip_db)
    assert result.hi_types == ["OPConsultation"]
    assert result.artefact.consent_artefact_id == "ART-1"


async def test_an_artefact_we_never_saw_is_refused(hip_db):
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db, consent_artefact_id="NEVER-HEARD-OF-IT")
    assert caught.value.code == "consent_not_valid"


async def test_a_revoked_artefact_is_refused_indistinguishably_from_an_absent_one(hip_db):
    """Same code and message on purpose. 'That consent exists but is revoked'
    versus 'no such consent' tells a caller which artefact ids are real, which
    is an enumeration oracle over other people's consents."""
    await _artefact(hip_db, status="revoked")

    with pytest.raises(service.HipError) as revoked:
        await _authorise(hip_db)
    with pytest.raises(service.HipError) as absent:
        await _authorise(hip_db, consent_artefact_id="DOES-NOT-EXIST")

    assert revoked.value.code == absent.value.code
    assert revoked.value.message == absent.value.message


async def test_an_expired_artefact_is_refused(hip_db):
    await _artefact(hip_db, expires=NOW - timedelta(seconds=1))
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db)
    assert caught.value.code == "consent_expired"


async def test_an_hi_type_outside_the_grant_is_refused(hip_db):
    await _artefact(hip_db, hi_types=["OPConsultation"])
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db, requested_hi_types=["OPConsultation", "DiagnosticReport"])
    assert caught.value.code == "hi_type_not_permitted"
    assert "DiagnosticReport" in caught.value.message


async def test_requesting_nothing_is_refused_rather_than_returning_everything(hip_db):
    """An empty type list must not fall through to 'no restriction'."""
    await _artefact(hip_db)
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db, requested_hi_types=[])
    assert caught.value.code == "hi_type_not_permitted"


@pytest.mark.parametrize(
    "frm, to",
    [
        (NOW - timedelta(days=400), NOW),
        (NOW, NOW + timedelta(days=400)),
    ],
    ids=["starts-before-grant", "ends-after-grant"],
)
async def test_a_period_outside_the_grant_is_refused_not_silently_clipped(hip_db, frm, to):
    """Clipping would return a shorter history than was asked for, with nothing
    saying so, and the HIU would file that as the patient's complete record."""
    await _artefact(hip_db)
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db, requested_from=frm, requested_to=to)
    assert caught.value.code == "date_range_not_permitted"


async def test_another_facilitys_artefact_does_not_authorise_our_records(hip_db):
    """One deployment, many facilities. An artefact notified to one is not
    authority over another's records."""
    await _artefact(hip_db, facility_id=OTHER_FACILITY)
    with pytest.raises(service.HipError) as caught:
        await _authorise(hip_db, facility_id=FACILITY)
    assert caught.value.code == "consent_not_valid"


async def test_a_naive_timestamp_does_not_crash_the_gate(hip_db):
    """A TypeError comparing naive to aware would surface as a 500 on the one
    endpoint that must always give a definite answer."""
    await _artefact(hip_db, expires=datetime(2026, 12, 1))  # naive on purpose
    result = await _authorise(hip_db)
    assert result.artefact is not None


async def test_a_revoked_artefact_cannot_be_re_granted_by_a_replayed_notification(hip_db):
    """ABDM issues a NEW artefact on re-grant, so a 'granted' for an id we
    already revoked is a replay, and honouring it would undo a revocation."""
    await _artefact(hip_db, status="revoked")
    with pytest.raises(service.HipError) as caught:
        await service.record_consent_notification(
            hip_db, facility_id=FACILITY, artefact_id="ART-1",
            abha_address="someone@sbx", status="granted",
            hi_types=["OPConsultation"], date_range_from=None,
            date_range_to=None, expires_at=None, raw={},
        )
    assert caught.value.code == "consent_revoked"


async def test_a_revocation_for_an_unknown_artefact_is_still_recorded(hip_db):
    """The difference between 'we were told to stop and did' and 'we have no
    record of being told' is the whole question after a complaint."""
    row = await service.record_consent_notification(
        hip_db, facility_id=FACILITY, artefact_id="NEVER-GRANTED",
        abha_address="someone@sbx", status="revoked",
        hi_types=[], date_range_from=None, date_range_to=None,
        expires_at=None, raw={"note": "revocation for an artefact we never held"},
    )
    assert row.status == "revoked"


async def test_an_unrecognised_status_is_refused(hip_db):
    with pytest.raises(service.HipError) as caught:
        await service.record_consent_notification(
            hip_db, facility_id=FACILITY, artefact_id="ART-9",
            abha_address="someone@sbx", status="probably-fine",
            hi_types=[], date_range_from=None, date_range_to=None,
            expires_at=None, raw={},
        )
    assert caught.value.code == "unknown_status"
