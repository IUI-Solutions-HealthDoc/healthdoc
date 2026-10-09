"""Exercise the callback → committed request → separate worker-session boundary.

Only transport and document assembly are mocked. Consent/context selection and
the persisted request use the database, so a worker widening the range cannot
hide behind an assertion on the callback's earlier authorization call.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.abdm import callback_replies, external_router, job_runner
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import HipHealthInformationCallback
from app.integrations.abdm.hip import gateway, worker
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmHipConsentArtefact,
    AbdmHipHealthInformationRequest,
)
from app.opd.models import Encounter, Visit
from app.users.models import Facility
from tests.integrations.abdm_serving import serve


@pytest.fixture
async def transfer_case(db, seed, opd_visit, monkeypatch):
    dept, _, doctor = seed

    facility = await db.get(Facility, dept.facility_id)
    facility.hfr_facility_id = "TEST-HFR"
    serve(monkeypatch, "TEST-HFR")
    monkeypatch.setattr(
        callback_replies, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    first = await opd_visit()
    now = datetime.now(UTC)
    contexts = []
    for offset in (1, 10, 20):
        visit = Visit(
            id=uuid.uuid4(),
            visit_number=f"ABDM-{uuid.uuid4()}",
            patient_id=first.patient_id,
            facility_id=dept.facility_id,
            visit_type="opd",
            status="completed",
            visit_date=now - timedelta(days=40),
            created_by=doctor.id,
        )
        encounter = Encounter(
            id=uuid.uuid4(),
            visit_id=visit.id,
            facility_id=dept.facility_id,
            provider_user_id=doctor.id,
            created_by=doctor.id,
            started_at=now - timedelta(days=offset, hours=1),
            ended_at=now - timedelta(days=offset),
        )
        context = AbdmCareContext(
            id=uuid.uuid4(),
            facility_id=dept.facility_id,
            patient_id=first.patient_id,
            visit_id=visit.id,
            reference=f"encounter/{encounter.id}",
            display="Test record",
            hi_type="OPConsultation",
            created_by=doctor.id,
            document_at=now - timedelta(days=offset),
        )
        db.add_all([visit, encounter, context])
        contexts.append(context)
    artefact = AbdmHipConsentArtefact(
        id=uuid.uuid4(),
        facility_id=dept.facility_id,
        consent_artefact_id=str(uuid.uuid4()),
        abha_address="scope@sbx",
        status="granted",
        hi_types=["OPConsultation"],
        date_range_from=now - timedelta(days=30),
        date_range_to=now,
        expires_at=now + timedelta(days=1),
        raw_artefact={
            "consentDetail": {
                "careContexts": [{"careContextReference": c.reference} for c in contexts]
            }
        },
    )
    db.add_all(
        [
            artefact,
            AbdmCareContextLink(
                id=uuid.uuid4(),
                facility_id=dept.facility_id,
                patient_id=first.patient_id,
                abha_address="scope@sbx",
                status="confirmed",
                care_context_references=[c.reference for c in contexts],
            ),
        ]
    )
    await db.commit()
    monkeypatch.setattr(external_router, "_facility_id", AsyncMock(return_value=dept.facility_id))
    monkeypatch.setattr(gateway, "acknowledge_hi_request", AsyncMock())
    monkeypatch.setattr(worker, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False))
    monkeypatch.setattr(
        job_runner, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        worker, "_validate_data_push_url", AsyncMock(return_value="https://hiu.example/transfer")
    )
    monkeypatch.setattr(worker, "_clinical_facts", AsyncMock(return_value={}))
    monkeypatch.setattr(worker, "build_clinical_bundle", lambda *a, **kw: {})
    monkeypatch.setattr(
        worker.hip_service,
        "encrypt_bundle_for_hiu",
        lambda *a, **kw: (
            "test-ciphertext",
            {"dhPublicKey": {}},
            "test-checksum",
        ),
    )
    pushes = AsyncMock()
    monkeypatch.setattr(worker, "_post_page", pushes)
    monkeypatch.setattr(worker, "_notify_gateway", AsyncMock())
    payload = HipHealthInformationCallback.model_validate(
        {
            "transactionId": str(uuid.uuid4()),
            "hiRequest": {
                "consent": {"id": artefact.consent_artefact_id},
                "dateRange": {"from": now - timedelta(days=11), "to": now - timedelta(days=9)},
                "dataPushUrl": "https://hiu.example/transfer",
                "keyMaterial": {
                    "cryptoAlg": "ECDH",
                    "curve": "Curve25519",
                    "nonce": "nonce",
                    "dhPublicKey": {
                        "expiry": now + timedelta(hours=1),
                        "parameters": "Curve25519",
                        "keyValue": "public",
                    },
                },
            },
        }
    )
    callback = GatewayCallback(str(uuid.uuid4()), now, "HIP-TEST")
    return payload, callback, contexts, pushes


async def test_worker_preserves_narrower_request_after_callback_commits(db, transfer_case):
    payload, callback, contexts, pushes = transfer_case
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)
    await tasks()
    assert [c.args[1]["entries"][0]["careContextReference"] for c in pushes.call_args_list] == [
        contexts[1].reference
    ]
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "delivered"
    assert row.requested_hi_types == ["OPConsultation"]
    assert worker._aware(row.requested_from) == payload.hi_request.date_range.from_
    assert worker._aware(row.requested_to) == payload.hi_request.date_range.to


async def test_worker_refuses_an_old_request_with_unknown_scope(db, transfer_case):
    payload, callback, _, pushes = transfer_case
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    # A pre-migration row cannot safely be backfilled from a broader artefact.
    row.requested_from = None
    row.requested_to = None
    row.requested_hi_types = None
    await db.commit()
    await tasks()
    pushes.assert_not_awaited()
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "failed"
    assert row.failure_reason == "Original transfer scope is unavailable; request data again"


async def _refused_before_any_page(db, transfer_case):
    payload, callback, _, _ = transfer_case
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    row.requested_from = row.requested_to = row.requested_hi_types = None
    await db.commit()
    await tasks()
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "failed"
    worker._notify_gateway.reset_mock()
    return row


async def test_failure_notice_names_the_consented_care_contexts(db, transfer_case):
    """30 September 2026: a transfer refused before any page was built was
    reported with careContextReference "", and NHA refused that notice."""
    references = [c.reference for c in transfer_case[2]]
    row = await _refused_before_any_page(db, transfer_case)
    await worker.notify_transaction(row.id)
    worker._notify_gateway.assert_awaited_once()
    sent = worker._notify_gateway.await_args.kwargs
    assert sent["session_status"] == "FAILED"
    assert [s["careContextReference"] for s in sent["statuses"]] == references
    assert {s["hiStatus"] for s in sent["statuses"]} == {"ERRORED"}


async def test_failure_notice_without_a_care_context_is_not_sent(db, transfer_case):
    row = await _refused_before_any_page(db, transfer_case)
    artefact = (
        await db.execute(
            select(AbdmHipConsentArtefact).where(
                AbdmHipConsentArtefact.consent_artefact_id == row.consent_artefact_id
            )
        )
    ).scalar_one()
    artefact.raw_artefact = {"consentDetail": {"careContexts": []}}
    await db.commit()
    with pytest.raises(worker.TransferError):
        await worker.notify_transaction(row.id)
    worker._notify_gateway.assert_not_awaited()


async def test_a_refused_push_records_the_hius_status_and_code(monkeypatch):
    """1 October 2026: ABDM's PHR refused a page with 400 ABDM-9999 and the
    worker kept only "failed after bounded retries"."""
    import httpx

    def refuse(request):
        return httpx.Response(
            400,
            json={
                "code": "ABDM-9999: ",
                "message": "Could not read encrypted content from input encoded key spec",
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        worker.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(refuse), **kw),
    )
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    # A 4xx is the HIU's verdict on this document; repeating it cannot help
    # and used to hold back every later page (7 Oct 2026).
    with pytest.raises(worker.PageRefused) as caught:
        await worker._post_page("https://hiu.example/transfer", {"entries": []})
    assert not isinstance(caught.value, worker.TransientTransferError)
    assert str(caught.value) == "HIU refused the document (HIU returned HTTP 400 ABDM-9999)"


async def test_unknown_document_dates_are_not_substituted_with_visit_dates(db, transfer_case):
    payload, callback, contexts, pushes = transfer_case
    contexts[1].document_at = None
    await db.commit()
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)
    await tasks()
    pushes.assert_not_awaited()


async def test_same_reference_on_an_unlinked_patient_is_not_shared(db, transfer_case, opd_visit):
    payload, callback, contexts, pushes = transfer_case
    other_visit = await opd_visit()
    original = contexts[1]
    db.add(
        AbdmCareContext(
            id=uuid.uuid4(),
            facility_id=original.facility_id,
            patient_id=other_visit.patient_id,
            visit_id=other_visit.id,
            reference=original.reference,
            display="Not linked",
            hi_type=original.hi_type,
            document_at=original.document_at,
            created_by=original.created_by,
        )
    )
    await db.commit()
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)
    await tasks()
    assert pushes.await_count == 1


@pytest.mark.parametrize(
    "change",
    [
        "revoke",
        "unlink",
        "remove_reference",
        "narrow_range",
        "remove_hi_type",
        "reopen_source",
        "redate_source",
        "reassign_source",
    ],
)
async def test_authorisation_is_rechecked_between_pages(db, transfer_case, change):
    payload, callback, contexts, pushes = transfer_case
    payload.hi_request.date_range.from_ -= timedelta(days=20)
    payload.hi_request.date_range.to += timedelta(days=9)
    # Keep this broader request within the original 30-day grant.
    artefact = (await db.execute(select(AbdmHipConsentArtefact))).scalar_one()
    payload.hi_request.date_range.from_ = worker._aware(artefact.date_range_from)
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(payload, tasks, callback, db)

    async def change_after_first_page(*args):
        if change == "revoke":
            artefact.status = "revoked"
        elif change == "narrow_range":
            artefact.date_range_from += timedelta(days=1)
        elif change == "remove_hi_type":
            artefact.hi_types = []
        elif change.endswith("source"):
            # A separate transaction changes the source after the worker has
            # already loaded all documents. Its identity map is now stale.
            values = {"ended_at": None}
            if change == "redate_source":
                values = {"ended_at": datetime.now(UTC)}
            elif change == "reassign_source":
                values = {"visit_id": contexts[0].visit_id}
            await db.execute(update(Encounter).values(**values))
        else:
            link = (await db.execute(select(AbdmCareContextLink))).scalar_one()
            if change == "unlink":
                link.status = "pending"
            else:
                link.care_context_references = []
        await db.commit()

    pushes.side_effect = change_after_first_page
    await tasks()
    assert pushes.await_count == 1
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "failed"
    assert row.bundles_sent == "1"


async def test_an_hiu_that_does_not_know_the_transaction_yet_is_waited_for(monkeypatch):
    """Live, 3 Oct 2026: our push reached our own HIU before NHA's on-request
    told it the transaction, and every page attempt got 404."""
    import httpx

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        worker.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404, json={})), **kw
        ),
    )
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    with pytest.raises(worker.HiuTransactionUnknown):
        await worker._post_page("https://hiu.example/transfer", {"entries": []})


def _whole_range(payload):
    now = datetime.now(UTC)
    payload.hi_request.date_range.from_ = now - timedelta(days=29)
    payload.hi_request.date_range.to = now - timedelta(hours=1)
    return payload


async def test_a_refused_document_does_not_hold_back_the_others(db, transfer_case):
    # 7 Oct 2026: the HIU refused one X-ray report (422, then 409 on every
    # retry) and the six records after it were never sent.
    payload, callback, contexts, pushes = transfer_case
    pushes.side_effect = [worker.PageRefused("HIU refused the document (HIU returned HTTP 422)")] + [
        None
    ] * (len(contexts) - 1)
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(_whole_range(payload), tasks, callback, db)
    await tasks()
    assert pushes.await_count == len(contexts) > 1
    refused = pushes.call_args_list[0].args[1]["entries"][0]["careContextReference"]
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "delivered"
    assert row.bundles_sent == str(len(contexts) - 1)
    assert refused in row.failure_reason


async def test_a_transfer_whose_every_document_is_refused_fails(db, transfer_case):
    payload, callback, contexts, pushes = transfer_case
    pushes.side_effect = worker.PageRefused("HIU refused the document (HIU returned HTTP 422)")
    tasks = BackgroundTasks()
    await external_router.hip_health_information_request(_whole_range(payload), tasks, callback, db)
    await tasks()
    db.expire_all()
    row = (await db.execute(select(AbdmHipHealthInformationRequest))).scalar_one()
    assert row.status == "failed"
    assert row.failure_reason == "The HIU refused every document"


def _revocation(consent_id: str, status: str = "REVOKED"):
    from app.integrations.abdm.contracts_v3 import HipConsentCallback

    # The shape ABDM sent on 7 Oct 2026: status and consentId, no consentDetail.
    return HipConsentCallback.model_validate(
        {"notification": {"status": status, "consentId": consent_id}}
    )


async def _artefact(db):
    return (await db.execute(select(AbdmHipConsentArtefact))).scalar_one()


@pytest.mark.parametrize("status", ["REVOKED", "EXPIRED"])
async def test_a_revocation_without_consent_detail_stops_sharing(db, transfer_case, status):
    payload, callback, _, pushes = transfer_case
    artefact = await _artefact(db)
    await external_router.hip_consent_notify(
        _revocation(artefact.consent_artefact_id, status), callback, db)
    db.expire_all()
    assert (await _artefact(db)).status == status.lower()
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await external_router.hip_health_information_request(
            payload, BackgroundTasks(), GatewayCallback(str(uuid.uuid4()), datetime.now(UTC), "HIP-TEST"), db)
    pushes.assert_not_awaited()


async def test_a_grant_still_needs_its_consent_detail(db, transfer_case):
    from fastapi import HTTPException

    _, callback, _, _ = transfer_case
    with pytest.raises(HTTPException) as caught:
        await external_router.hip_consent_notify(_revocation(str(uuid.uuid4()), "GRANTED"), callback, db)
    assert caught.value.status_code == 422


async def test_a_revocation_for_an_unknown_consent_is_acknowledged(db, transfer_case):
    _, callback, _, _ = transfer_case
    before = (await _artefact(db)).status
    response = await external_router.hip_consent_notify(_revocation(str(uuid.uuid4())), callback, db)
    assert response.status_code == 202
    db.expire_all()
    assert (await _artefact(db)).status == before == "granted"
