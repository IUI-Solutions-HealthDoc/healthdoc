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


# ---------------------------------------------------------------------------
# Callback replay safety.
#
# The gateway does not send our Idempotency-Key — it identifies a retry by its
# own REQUEST-ID — so these routes cannot require the header the rest of the
# app does. They have to be replay-safe by construction instead, and this is
# where that is checked.
# ---------------------------------------------------------------------------


@pytest.fixture
def hip_client(hip_db):
    """TestClient with the callback gate opened and the fixture session bound."""
    from fastapi.testclient import TestClient

    from app.common.db import get_db
    from app.integrations.abdm.callback_auth import verify_callback
    from app.main import app

    async def _db():
        yield hip_db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[verify_callback] = lambda: None
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(verify_callback, None)


async def _facility_with_hfr(db, hfr_id="HFR-1"):
    await db.execute(
        text("UPDATE facilities SET hfr_facility_id = :h WHERE id = :i"),
        {"h": hfr_id, "i": str(FACILITY)},
    )
    await db.flush()


def _hi_request_body(**over):
    return {
        "hip_id": "HFR-1",
        "transaction_id": "TXN-REPLAY-1",
        "consent_artefact_id": "ART-1",
        "abha_address": "someone@sbx",
        "hi_types": ["OPConsultation"],
        "data_push_url": "https://hiu.example/transfer",
        "key_material": {"dhPublicKey": {"keyValue": "k"}, "nonce": "n"},
        **over,
    }


async def test_a_retried_health_information_request_replays_instead_of_500ing(
    hip_db, hip_client
):
    """transaction_id is UNIQUE. Without this guard a gateway retry hits an
    integrity error, comes back 500, and the gateway reads that as 'try again'
    — a retry loop against a request already accepted."""
    await _facility_with_hfr(hip_db)
    await _artefact(hip_db)

    first = hip_client.post(
        "/api/v1/abdm/hip/callbacks/health-information/request", json=_hi_request_body()
    )
    assert first.status_code == 202, first.text
    assert first.json()["data"].get("replayed") is None

    second = hip_client.post(
        "/api/v1/abdm/hip/callbacks/health-information/request", json=_hi_request_body()
    )
    assert second.status_code == 202, second.text
    assert second.json()["data"]["replayed"] is True
    assert second.json()["data"]["accepted"] == first.json()["data"]["accepted"]


async def test_a_retried_request_that_was_refused_stays_refused(hip_db, hip_client):
    """A replay must not become a second chance at the consent gate."""
    await _facility_with_hfr(hip_db)
    await _artefact(hip_db, status="revoked")

    first = hip_client.post(
        "/api/v1/abdm/hip/callbacks/health-information/request", json=_hi_request_body()
    )
    assert first.status_code == 403

    second = hip_client.post(
        "/api/v1/abdm/hip/callbacks/health-information/request", json=_hi_request_body()
    )
    assert second.status_code == 403


async def test_a_callback_for_an_unknown_hfr_id_is_refused(hip_db, hip_client):
    """Otherwise another organisation's callback is attributed to whichever
    facility happens to be first in the table."""
    await _facility_with_hfr(hip_db)
    response = hip_client.post(
        "/api/v1/abdm/hip/callbacks/health-information/request",
        json=_hi_request_body(hip_id="SOMEONE-ELSE"),
    )
    assert response.status_code == 404
