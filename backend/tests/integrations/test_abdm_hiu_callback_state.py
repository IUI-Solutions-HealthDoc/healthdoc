"""Delayed callbacks must not reopen permission or cross facility boundaries."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.integrations.abdm import callback_replies, jobs
from app.integrations.abdm import external_router as routes
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import (
    ConsentOnFetchCallback,
    ConsentOnInitCallback,
    ConsentOnStatusCallback,
    HiuConsentNotifyCallback,
    HiuHealthInformationOnRequestCallback,
)
from app.integrations.abdm.hiu import service, worker
from app.integrations.abdm.hiu.models import AbdmConsentRequest
from app.integrations.abdm.jobs import AbdmJob
from tests.integrations.test_abdm_hiu_key_lifecycle import (
    ACTOR,
    FACILITY,
    NOW,
    _granted_artefact,
)
from tests.integrations.test_abdm_hiu_key_lifecycle import (
    hiu_db as hiu_fixture,
)

hiu_db = hiu_fixture


@pytest.mark.parametrize("kind", ["hiu_consent", "hiu_request", "hiu_notify"])
async def test_outbound_job_cannot_use_another_facilitys_bridge(hiu_db, monkeypatch, kind):
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(
        worker, "SessionLocal", async_sessionmaker(hiu_db.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(abdm_hfr_facility_id="OTHER-HFR")
    )
    calls = [AsyncMock(), AsyncMock(), AsyncMock()]
    for name, call in zip(
        ("request_consent", "request_health_information", "notify_hi_receipt"), calls, strict=True
    ):
        monkeypatch.setattr(worker.gateway, name, call)
    await hiu_db.commit()
    with pytest.raises(ValueError, match="Facility is not configured"):
        await worker.dispatch(
            AbdmJob(id=uuid.uuid4(), kind=kind, target_id=uuid.uuid4(), facility_id=FACILITY)
        )
    for call in calls:
        call.assert_not_awaited()


@pytest.fixture
async def callback_case(hiu_db, monkeypatch):
    artefact = await _granted_artefact(hiu_db)
    request = await hiu_db.get(AbdmConsentRequest, artefact.consent_request_id)
    request.gateway_request_id = str(uuid.uuid4())
    request.consent_request_id = str(uuid.uuid4())
    request.status = "granted"
    transfer, _ = await service.begin_hi_request(
        hiu_db, facility_id=FACILITY, artefact=artefact, created_by=ACTOR, now=NOW
    )
    transfer.gateway_request_id = str(uuid.uuid4())
    transfer.transaction_id = str(uuid.uuid4())
    await hiu_db.flush()
    await jobs.enqueue(hiu_db, kind="hiu_fetch", target_id=artefact.id, facility_id=FACILITY)
    fetch = await hiu_db.get(AbdmJob, jobs.job_id("hiu_fetch", artefact.id))
    fetch.attempts = 1
    callback = GatewayCallback(str(uuid.uuid4()), datetime.now(UTC), "TEST-HIU")
    monkeypatch.setattr(routes, "_facility_id", AsyncMock(return_value=FACILITY))
    monkeypatch.setattr(callback_replies.hiu_gateway, "fetch_consent_artefact", AsyncMock())
    monkeypatch.setattr(
        callback_replies.hiu_gateway, "acknowledge_consent_notification", AsyncMock()
    )
    return request, artefact, transfer, callback


def fetch_payload(request, artefact):
    return ConsentOnFetchCallback.model_validate(
        {
            "response": {"requestId": str(jobs.job_id("hiu_fetch", artefact.id))},
            "consent": {
                "status": "GRANTED",
                "consentDetail": {
                    "consentId": artefact.consent_artefact_id,
                    "patient": {"id": request.abha_address},
                    "hip": {"id": "TEST-HIP"},
                    "hiu": {"id": "TEST-HIU"},
                    "hiTypes": list(request.hi_types),
                    "permission": {
                        "dateRange": {
                            "from": request.date_range_from,
                            "to": request.date_range_to,
                        },
                        "dataEraseAt": request.requested_expiry,
                    },
                },
            },
        }
    )


async def test_artefact_fetch_must_match_a_dispatched_job(hiu_db, callback_case):
    request, artefact, _, callback = callback_case
    payload = fetch_payload(request, artefact)
    payload.response.request_id = str(uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes.consent_on_fetch(payload, callback, hiu_db)
    assert caught.value.status_code == 409
    payload.response.request_id = str(jobs.job_id("hiu_fetch", artefact.id))
    fetch = await hiu_db.get(AbdmJob, jobs.job_id("hiu_fetch", artefact.id))
    fetch.attempts = 0
    with pytest.raises(HTTPException) as caught:
        await routes.consent_on_fetch(payload, callback, hiu_db)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("route", ["init", "status", "notify", "fetch", "transfer"])
async def test_callback_correlation_is_facility_scoped(hiu_db, callback_case, monkeypatch, route):
    request, artefact, transfer, callback = callback_case
    monkeypatch.setattr(routes, "_facility_id", AsyncMock(return_value=uuid.uuid4()))
    handler, payload = {
        "init": (
            routes.consent_on_init,
            ConsentOnInitCallback.model_validate(
                {
                    "response": {"requestId": request.gateway_request_id},
                    "consentRequest": {"id": request.consent_request_id},
                }
            ),
        ),
        "status": (
            routes.consent_on_status,
            ConsentOnStatusCallback.model_validate(
                {
                    "response": {"requestId": request.gateway_request_id},
                    "consentRequest": {"id": request.consent_request_id, "status": "REVOKED"},
                }
            ),
        ),
        "notify": (
            routes.hiu_consent_notify,
            HiuConsentNotifyCallback.model_validate(
                {
                    "notification": {
                        "consentRequestId": request.consent_request_id,
                        "status": "REVOKED",
                    },
                }
            ),
        ),
        "fetch": (routes.consent_on_fetch, fetch_payload(request, artefact)),
        "transfer": (
            routes.hiu_health_information_on_request,
            HiuHealthInformationOnRequestCallback.model_validate(
                {
                    "response": {"requestId": transfer.gateway_request_id},
                    "hiRequest": {
                        "transactionId": transfer.transaction_id,
                        "sessionStatus": "ACKNOWLEDGED",
                    },
                }
            ),
        ),
    }[route]
    with pytest.raises(HTTPException) as caught:
        await handler(payload, callback, hiu_db)
    assert caught.value.status_code == 404
    assert request.status == "granted" and transfer.status == "requested"


@pytest.mark.parametrize("state", ["acknowledged", "partial", "received", "expired", "failed"])
@pytest.mark.parametrize("reply", ["ack", "error"])
async def test_late_data_request_reply_does_not_rewind_transfer(
    hiu_db, callback_case, state, reply
):
    _, _, transfer, callback = callback_case
    transfer.status = state
    body = {"response": {"requestId": transfer.gateway_request_id}}
    if reply == "ack":
        body["hiRequest"] = {
            "transactionId": transfer.transaction_id,
            "sessionStatus": "ACKNOWLEDGED",
        }
    else:
        body["error"] = {"code": "TEST-ERROR", "message": "Synthetic late error"}
    await routes.hiu_health_information_on_request(
        HiuHealthInformationOnRequestCallback.model_validate(body), callback, hiu_db
    )
    assert transfer.status == state


async def test_changed_transaction_is_refused_and_rejection_clears_keys(hiu_db, callback_case):
    _, _, transfer, callback = callback_case
    payload = HiuHealthInformationOnRequestCallback.model_validate(
        {
            "response": {"requestId": transfer.gateway_request_id},
            "hiRequest": {"transactionId": str(uuid.uuid4()), "sessionStatus": "ACKNOWLEDGED"},
        }
    )
    with pytest.raises(HTTPException) as caught:
        await routes.hiu_health_information_on_request(payload, callback, hiu_db)
    assert caught.value.status_code == 409
    transfer.transaction_id = None
    payload.hi_request = None
    await routes.hiu_health_information_on_request(payload, callback, hiu_db)
    assert transfer.status == "failed"
    assert transfer.private_key_encrypted is transfer.key_version is None


@pytest.mark.parametrize("state", ["revoked", "expired", "denied", "failed"])
async def test_late_grant_does_not_reopen_consent(hiu_db, callback_case, state):
    request, artefact, _, callback = callback_case
    request.status = state
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {
                "consentRequestId": request.consent_request_id,
                "status": "GRANTED",
                "consentArtefacts": [{"id": artefact.consent_artefact_id}],
            },
        }
    )
    await routes.hiu_consent_notify(payload, callback, hiu_db)
    assert request.status == state
    callback_replies.hiu_gateway.fetch_consent_artefact.assert_not_awaited()
    callback_replies.hiu_gateway.acknowledge_consent_notification.assert_not_awaited()
    from sqlalchemy import select

    assert (await hiu_db.execute(select(jobs.AbdmCallbackReply))).scalar_one().kind == "hiu_consent"


@pytest.mark.parametrize("change", ["patient", "hiu", "no_hiu", "type", "from", "to", "expiry"])
async def test_fetched_grant_cannot_change_patient_or_widen_request(hiu_db, callback_case, change):
    request, artefact, _, callback = callback_case
    payload = fetch_payload(request, artefact)
    detail = payload.consent.consent_detail
    if change == "patient":
        detail.patient.id = "not-this-patient@sbx"
    elif change == "hiu":
        detail.hiu.id = "NOT-THIS-HIU"
    elif change == "no_hiu":
        # Optional on the wire since NHA's HIP notification omits it; an HIU
        # grant without one is still not ours to accept.
        detail.hiu = None
    elif change == "type":
        detail.hi_types = ["Prescription"]
    elif change == "from":
        detail.permission.date_range.from_ -= timedelta(days=1)
    elif change == "to":
        detail.permission.date_range.to += timedelta(days=1)
    else:
        detail.permission.data_erase_at += timedelta(days=1)
    original = artefact.raw_artefact
    with pytest.raises(HTTPException) as caught:
        await routes.consent_on_fetch(payload, callback, hiu_db)
    assert caught.value.status_code == 422
    assert artefact.raw_artefact == original


async def test_duplicate_announcement_keeps_fetched_scope(hiu_db, callback_case):
    request, artefact, _, callback = callback_case
    original = artefact.raw_artefact
    payload = HiuConsentNotifyCallback.model_validate(
        {
            "notification": {
                "consentRequestId": request.consent_request_id,
                "status": "GRANTED",
                "consentArtefacts": [{"id": artefact.consent_artefact_id}],
            },
        }
    )
    await routes.hiu_consent_notify(payload, callback, hiu_db)
    assert artefact.raw_artefact == original
    assert artefact.hi_types == ["OPConsultation"] and artefact.expires_at is not None


@pytest.mark.parametrize("route", ["status", "notify"])
async def test_request_wide_revocation_without_artefact_list_clears_open_keys(
    hiu_db, callback_case, route
):
    request, artefact, transfer, callback = callback_case
    transfer.status = "partial"
    if route == "status":
        await routes.consent_on_status(
            ConsentOnStatusCallback.model_validate(
                {
                    "response": {"requestId": request.gateway_request_id},
                    "consentRequest": {"id": request.consent_request_id, "status": "REVOKED"},
                }
            ),
            callback,
            hiu_db,
        )
    else:
        await routes.hiu_consent_notify(
            HiuConsentNotifyCallback.model_validate(
                {
                    "notification": {
                        "consentRequestId": request.consent_request_id,
                        "status": "REVOKED",
                    },
                }
            ),
            callback,
            hiu_db,
        )
    assert request.status == artefact.status == "revoked"
    assert transfer.status == "expired"
    assert transfer.private_key_encrypted is transfer.key_version is None


@pytest.mark.parametrize("change", ["owner", "facility", "expired"])
async def test_artefact_service_refuses_rebinding_and_regrant(hiu_db, callback_case, change):
    request, artefact, _, _ = callback_case
    facility = FACILITY
    if change == "owner":
        other = await _granted_artefact(hiu_db)
        request = await hiu_db.get(AbdmConsentRequest, other.consent_request_id)
    elif change == "facility":
        facility = uuid.uuid4()
    else:
        artefact.status = "expired"
    with pytest.raises(service.HiuError):
        await service.record_artefact(
            hiu_db,
            facility_id=facility,
            consent_request=request,
            artefact_id=artefact.consent_artefact_id,
            status="granted",
            hi_types=["OPConsultation"],
            date_range_from=request.date_range_from,
            date_range_to=request.date_range_to,
            expires_at=request.requested_expiry,
            raw={},
        )


async def _undecided(hiu_db, callback_case):
    request, artefact, _, callback = callback_case
    await hiu_db.delete(artefact)
    request.status, request.consent_request_id = "requested", None
    await hiu_db.flush()
    return request, callback


async def test_on_init_asks_for_the_status_a_decision_may_already_have(hiu_db, callback_case):
    """Live, 3 Oct 2026: GRANTED arrived 30 s after the request and on-init 16
    min later, so the grant could not be matched and was refused."""
    request, callback = await _undecided(hiu_db, callback_case)
    remote = str(uuid.uuid4())
    await routes.consent_on_init(
        ConsentOnInitCallback.model_validate(
            {"consentRequest": {"id": remote}, "response": {"requestId": request.gateway_request_id}}
        ),
        callback,
        hiu_db,
    )
    assert request.consent_request_id == remote
    job = await hiu_db.get(AbdmJob, jobs.job_id("hiu_consent", request.id))
    assert (job.status, job.attempts) == ("pending", 0)


async def test_the_consent_job_polls_status_once_the_id_is_known(hiu_db, callback_case, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker

    request, _ = await _undecided(hiu_db, callback_case)
    request.consent_request_id = remote = str(uuid.uuid4())
    await hiu_db.commit()
    monkeypatch.setattr(worker, "SessionLocal", async_sessionmaker(hiu_db.bind, expire_on_commit=False))
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(abdm_hfr_facility_id="TEST-HFR"))
    status, consent = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker.gateway, "check_consent_request_status", status)
    monkeypatch.setattr(worker.gateway, "request_consent", consent)
    await worker.dispatch(
        AbdmJob(id=uuid.uuid4(), kind="hiu_consent", target_id=request.id, facility_id=FACILITY)
    )
    consent.assert_not_awaited()
    assert status.await_args.kwargs["consent_request_id"] == remote


async def test_a_status_grant_is_matched_by_id_and_its_artefact_fetched(hiu_db, callback_case):
    request, callback = await _undecided(hiu_db, callback_case)
    request.consent_request_id = remote = str(uuid.uuid4())
    await hiu_db.flush()
    granted = str(uuid.uuid4())
    await routes.consent_on_status(
        ConsentOnStatusCallback.model_validate(
            {
                # The poll's own REQUEST-ID, not the original request's.
                "response": {"requestId": str(uuid.uuid4())},
                "consentRequest": {
                    "id": remote,
                    "status": "GRANTED",
                    "consentArtefacts": [{"id": granted}],
                },
            }
        ),
        callback,
        hiu_db,
    )
    assert request.status == "granted"
    artefact = (
        await hiu_db.execute(
            select(service.AbdmHiuConsentArtefact).where(
                service.AbdmHiuConsentArtefact.consent_artefact_id == granted
            )
        )
    ).scalar_one()
    assert artefact.status == "granted" and artefact.consent_request_id == request.id
    fetch = await hiu_db.get(AbdmJob, jobs.job_id("hiu_fetch", artefact.id))
    assert fetch is not None and fetch.status == "pending"


async def test_a_status_for_an_unknown_consent_is_still_refused(hiu_db, callback_case):
    _, callback = await _undecided(hiu_db, callback_case)
    with pytest.raises(HTTPException) as refused:
        await routes.consent_on_status(
            ConsentOnStatusCallback.model_validate(
                {
                    "response": {"requestId": str(uuid.uuid4())},
                    "consentRequest": {"id": str(uuid.uuid4()), "status": "GRANTED"},
                }
            ),
            callback,
            hiu_db,
        )
    assert refused.value.status_code == 404


@pytest.mark.parametrize("session_status", ["REQUESTED", "ACKNOWLEDGED"])
async def test_the_consent_managers_requested_keeps_the_transfer_open(
    hiu_db, callback_case, session_status
):
    """Live, 3 Oct 2026: on-request said REQUESTED, which was read as failure."""
    request, artefact, transfer, callback = callback_case
    transfer.status, transfer.transaction_id = "requested", None
    await hiu_db.flush()
    await routes.hiu_health_information_on_request(
        HiuHealthInformationOnRequestCallback.model_validate(
            {
                "response": {"requestId": transfer.gateway_request_id},
                "hiRequest": {"transactionId": str(uuid.uuid4()), "sessionStatus": session_status},
            }
        ),
        callback,
        hiu_db,
    )
    assert transfer.status == "acknowledged"
    assert transfer.private_key_encrypted is not None


async def test_an_unknown_session_status_fails_and_says_which(hiu_db, callback_case):
    request, artefact, transfer, callback = callback_case
    transfer.status, transfer.transaction_id = "requested", None
    await hiu_db.flush()
    await routes.hiu_health_information_on_request(
        HiuHealthInformationOnRequestCallback.model_validate(
            {
                "response": {"requestId": transfer.gateway_request_id},
                "hiRequest": {"transactionId": str(uuid.uuid4()), "sessionStatus": "ERRORED"},
            }
        ),
        callback,
        hiu_db,
    )
    assert transfer.status == "failed"
    assert transfer.failure_reason == "ABDM session status ERRORED"
