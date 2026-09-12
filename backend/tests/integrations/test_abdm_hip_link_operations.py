import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.db import get_db
from app.integrations.abdm import callback_auth, external_router, job_runner, jobs
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import GenericCallback, LinkTokenCallback
from app.integrations.abdm.hip import gateway, linking
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.integrations.abdm.hip.recovery import queue_token_callback_retry
from app.patients.models import Patient
from tests.integrations.test_abdm_callback_auth import _ReplayStore
from tests.integrations.test_abdm_document_exports import documents as documents_fixture

documents = documents_fixture


@pytest.fixture
async def link_case(db, documents, monkeypatch):
    facility, encounters, prescriptions, _, context = documents
    contexts = [
        context("encounter", encounters[0].id, "OPConsultation"),
        context("prescription", prescriptions[0].id, "Prescription"),
    ]
    db.add_all(contexts)
    patient = await db.get(Patient, contexts[0].patient_id)
    patient.abha_address = "link-test@sbx"
    patient.abha_linked_at = datetime.now(UTC)
    patient.dob = date(1990, 1, 1)
    patient.sex = "male"
    await db.flush()
    monkeypatch.setattr(
        job_runner, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        job_runner,
        "get_settings",
        lambda: SimpleNamespace(abdm_hfr_facility_id=facility.hfr_facility_id),
    )
    monkeypatch.setattr(external_router, "_facility_id", AsyncMock(return_value=facility.id))
    monkeypatch.setattr(gateway, "generate_link_token", AsyncMock())
    monkeypatch.setattr(gateway, "link_care_contexts", AsyncMock())
    return patient, contexts


def callback():
    return GatewayCallback(str(uuid.uuid4()), datetime.now(UTC), "HIP-TEST")


async def test_independent_actions_keep_independent_token_and_callback_correlations(db, link_case):
    patient, contexts = link_case
    links = []
    for context in contexts:
        links.extend(
            await linking.initiate(
                db,
                patient=patient,
                context_ids=[context.id],
                idempotency_key=f"action-{context.id}",
            )
        )
    assert len(links) == 2
    link_ids = [link.id for link in links]
    token_ids = [link.token_request_id for link in links]
    context_ids = [link.gateway_request_id for link in links]
    assert len(set(token_ids + context_ids)) == 4
    await db.commit()
    for ident in link_ids:
        await job_runner.run_once(jobs.job_id("link_token", ident))
    assert gateway.generate_link_token.await_count == 2
    for link in reversed(links):
        payload = LinkTokenCallback.model_validate(
            {
                "abhaAddress": patient.abha_address,
                "linkToken": "synthetic-test-token",
                "response": {"requestId": link.token_request_id},
            }
        )
        await external_router.generated_link_token(payload, callback(), db)
        await db.commit()
        assert (
            link.link_token_encrypted is not None
            and b"synthetic-test-token" not in link.link_token_encrypted
        )
        await job_runner.run_once(jobs.job_id("link_context", link.id))
    assert gateway.link_care_contexts.await_count == 2
    assert {call.kwargs["hi_type"] for call in gateway.link_care_contexts.call_args_list} == {
        "OPConsultation",
        "Prescription",
    }
    # Success arrives for the second type first; it cannot confirm the first.
    await external_router.on_care_context(
        GenericCallback.model_validate({"response": {"requestId": context_ids[1]}}), callback(), db
    )
    assert links[1].status == "confirmed" and links[0].status == "pending"
    failed = GenericCallback.model_validate(
        {
            "response": {"requestId": context_ids[0]},
            "error": {"code": "TEST_FAILURE", "message": "Synthetic refusal"},
        }
    )
    await external_router.on_care_context(failed, callback(), db)
    assert links[0].status == "failed" and links[1].status == "confirmed"
    await external_router.on_care_context(
        GenericCallback.model_validate({"response": {"requestId": context_ids[0]}}), callback(), db
    )
    assert links[0].status == "failed"  # replay cannot undo terminal refusal
    assert all(link.link_token_encrypted is None for link in links)
    assert [link.token_request_id for link in links] == token_ids


async def test_initiation_replay_does_not_create_duplicate_operations(db, link_case):
    patient, contexts = link_case
    first = await linking.initiate(
        db, patient=patient, context_ids=[c.id for c in contexts], idempotency_key="same"
    )
    second = await linking.initiate(
        db, patient=patient, context_ids=[c.id for c in contexts], idempotency_key="same"
    )
    assert [link.id for link in first] == [link.id for link in second]
    assert len((await db.execute(select(AbdmCareContextLink))).scalars().all()) == 1


async def test_multitype_selection_uses_one_token_and_one_grouped_link_request(db, link_case):
    patient, contexts = link_case
    links = await linking.initiate(
        db, patient=patient, context_ids=[c.id for c in contexts], idempotency_key="mixed-types"
    )
    assert len(links) == 1, "HI type is a payload group, not another token generation"
    link = links[0]
    assert link.care_context_references == sorted(c.reference for c in contexts)
    assert link.token_request_id != link.gateway_request_id
    await db.commit()
    assert await job_runner.run_once(jobs.job_id("link_token", link.id))
    gateway.generate_link_token.assert_awaited_once()
    await linking.accept_token(db, link, "synthetic-token", patient.abha_address)
    await db.commit()
    assert await job_runner.run_once(jobs.job_id("link_context", link.id))
    gateway.link_care_contexts.assert_awaited_once()
    assert gateway.link_care_contexts.call_args.kwargs["groups"] == {
        c.hi_type: [{"referenceNumber": c.reference, "display": c.display}] for c in contexts
    }
    assert link.status == "pending"
    await external_router.on_care_context(
        GenericCallback.model_validate({"response": {"requestId": link.gateway_request_id}}),
        callback(),
        db,
    )
    assert link.status == "confirmed" and link.link_token_encrypted is None


async def test_changed_type_selection_cannot_reuse_an_idempotency_key(db, link_case):
    patient, contexts = link_case
    await linking.initiate(
        db, patient=patient, context_ids=[contexts[0].id], idempotency_key="changed-types"
    )
    with pytest.raises(linking.DocumentUnavailable):
        await linking.initiate(
            db,
            patient=patient,
            context_ids=[c.id for c in contexts],
            idempotency_key="changed-types",
        )
    assert len((await db.execute(select(AbdmCareContextLink))).scalars().all()) == 1


async def test_legacy_per_type_replay_keeps_original_ids_and_attempts(db, link_case):
    patient, contexts = link_case
    old_ids = []
    for context in contexts:
        ident = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"healthdoc:hip-link:{patient.facility_id}:{patient.id}:legacy:{context.hi_type}",
        )
        old_ids.append(ident)
        db.add(
            AbdmCareContextLink(
                id=ident,
                facility_id=patient.facility_id,
                patient_id=patient.id,
                abha_address=patient.abha_address,
                care_context_references=[context.reference],
                status="pending",
                token_request_id=str(jobs.job_id("link_token", ident)),
                gateway_request_id=str(jobs.job_id("link_context", ident)),
            )
        )
        await db.flush()
        await jobs.enqueue(db, kind="link_token", target_id=ident, facility_id=patient.facility_id)
        job = await db.get(jobs.AbdmJob, jobs.job_id("link_token", ident))
        job.status, job.attempts = "done", 1
    await db.commit()
    replay = await linking.initiate(
        db, patient=patient, context_ids=[c.id for c in contexts], idempotency_key="legacy"
    )
    assert {row.id for row in replay} == set(old_ids)
    rows = (await db.execute(select(jobs.AbdmJob))).scalars().all()
    assert len(rows) == 2 and all(row.status == "done" and row.attempts == 1 for row in rows)
    gateway.generate_link_token.assert_not_awaited()
    with pytest.raises(linking.DocumentUnavailable):
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="legacy"
        )


async def test_wrong_patient_token_is_not_persisted_or_dispatched(db, link_case):
    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="wrong"
        )
    )[0]
    with pytest.raises(linking.DocumentUnavailable):
        await linking.accept_token(db, link, "synthetic-test-token", "another@sbx")
    assert link.link_token_encrypted is None
    assert (await db.get(jobs.AbdmJob, jobs.job_id("link_context", link.id))) is None


async def test_linking_http_callbacks_accept_the_m2_documented_header_set(
    db, link_case, monkeypatch
):
    """No dependency override for callback validation: exercise the real routes.

    M2 v2.8 token/link responses list REQUEST-ID, TIMESTAMP, X-HIP-ID and
    Authorization, not X-CM-ID. Body correlation and token identity still apply.
    Only the database and external services are synthetic.
    """
    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="http-callback"
        )
    )[0]
    monkeypatch.setattr(callback_auth, "get_redis", lambda: replay)
    monkeypatch.setattr(
        callback_auth,
        "get_settings",
        lambda: SimpleNamespace(abdm_hip_id="HIP-TEST", abdm_x_cm_id="sbx"),
    )
    replay = _ReplayStore()
    app = FastAPI()
    app.include_router(external_router.router)

    async def test_db():
        yield db

    app.dependency_overrides[get_db] = test_db

    def headers():
        return {
            "REQUEST-ID": str(uuid.uuid4()),
            "TIMESTAMP": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "X-HIP-ID": "HIP-TEST",
            "Authorization": "Bearer synthetic-callback-token",
        }

    body = {
        "abhaAddress": patient.abha_address,
        "linkToken": "synthetic-link-token",
        "response": {"requestId": link.token_request_id},
    }
    token_path = "/api/v3/hip/token/on-generate-token"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unknown = {**body, "response": {"requestId": str(uuid.uuid4())}}
        response = await client.post(token_path, json=unknown, headers=headers())
        assert response.status_code == 404, response.text
        wrong_patient = {**body, "abhaAddress": "other-patient@sbx"}
        response = await client.post(token_path, json=wrong_patient, headers=headers())
        assert response.status_code == 422, response.text
        assert link.link_token_encrypted is None
        response = await client.post(token_path, json=body, headers=headers())
        assert response.status_code == 202, response.text
        assert response.content == b""
        assert link.link_token_encrypted is not None
        assert (await db.get(jobs.AbdmJob, jobs.job_id("link_context", link.id))) is not None
        response = await client.post(
            "/api/v3/link/on_carecontext",
            headers=headers(),
            json={
                "abhaAddress": patient.abha_address,
                "status": "Successfully Linked care context",
                "response": {"requestId": link.gateway_request_id},
            },
        )
        assert response.status_code == 202, response.text
        assert response.content == b""
        assert link.status == "confirmed"
        assert link.link_token_encrypted is None


async def test_route_idempotency_rejects_adding_another_hi_type_under_the_same_key(db, link_case):
    from fastapi import HTTPException

    from app.integrations.abdm.hip.router import LinkDocumentsIn, initiate_links

    patient, contexts = link_case
    actor = SimpleNamespace(id=patient.created_by, facility_id=patient.facility_id)
    body = LinkDocumentsIn(context_ids=[contexts[0].id])
    first = await initiate_links(patient.id, body, actor, "same-operation", db)
    replay = await initiate_links(patient.id, body, actor, "same-operation", db)
    assert [link.id for link in first] == [link.id for link in replay]
    with pytest.raises(HTTPException) as caught:
        await initiate_links(
            patient.id,
            LinkDocumentsIn(context_ids=[c.id for c in contexts]),
            actor,
            "same-operation",
            db,
        )
    assert caught.value.status_code == 409


@pytest.fixture
async def lost_token(db, link_case):
    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="lost-callback"
        )
    )[0]
    job = await db.get(jobs.AbdmJob, jobs.job_id("link_token", link.id))
    job.status, job.attempts = "done", 1
    job.updated_at = datetime.now(UTC) - timedelta(minutes=11)
    await db.flush()
    return patient, link, job


async def test_lost_callback_recovery_is_explicit_once_and_preserves_correlation(db, lost_token):
    _, link, job = lost_token
    original_request = link.token_request_id
    assert (
        await queue_token_callback_retry(db, link_id=link.id, facility_id=link.facility_id)
        == job.id
    )
    assert job.status == "done" and job.attempts == 1  # preview sends/queues nothing
    await queue_token_callback_retry(db, link_id=link.id, facility_id=link.facility_id, apply=True)
    assert job.status == "pending" and job.attempts == 1
    assert job.last_error == jobs.TOKEN_CALLBACK_RECOVERY_MARKER
    assert link.token_request_id == original_request == str(job.id)
    with pytest.raises(linking.DocumentUnavailable):
        await queue_token_callback_retry(
            db, link_id=link.id, facility_id=link.facility_id, apply=True
        )


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_facility",
        "token_received",
        "confirmed",
        "failure",
        "too_soon",
        "attempts",
        "active_job",
        "wrong_correlation",
        "identity_changed",
        "context_job",
        "other_request",
    ],
)
async def test_lost_callback_recovery_refuses_unsafe_states(db, link_case, lost_token, problem):
    patient, link, job = lost_token
    facility_id = link.facility_id
    if problem == "wrong_facility":
        facility_id = uuid.uuid4()
    elif problem == "token_received":
        link.link_token_encrypted = b"synthetic"
    elif problem == "confirmed":
        link.status = "confirmed"
    elif problem == "failure":
        link.failure_reason = "SYNTHETIC_REFUSAL"
    elif problem == "too_soon":
        job.updated_at = datetime.now(UTC)
    elif problem == "attempts":
        job.attempts = 2
    elif problem == "active_job":
        job.status = "pending"
    elif problem == "wrong_correlation":
        link.token_request_id = str(uuid.uuid4())
    elif problem == "identity_changed":
        patient.abha_address = "changed@sbx"
    elif problem == "context_job":
        await jobs.enqueue(db, kind="link_context", target_id=link.id, facility_id=facility_id)
    elif problem == "other_request":
        await linking.initiate(
            db, patient=patient, context_ids=[link_case[1][1].id], idempotency_key="another-type"
        )
    await db.flush()
    with pytest.raises(linking.DocumentUnavailable):
        await queue_token_callback_retry(db, link_id=link.id, facility_id=facility_id, apply=True)


async def test_late_token_callback_prevents_regeneration(db, lost_token):
    _, link, job = lost_token
    await queue_token_callback_retry(db, link_id=link.id, facility_id=link.facility_id, apply=True)
    await linking.accept_token(db, link, "synthetic-late-token", link.abha_address)
    await db.commit()
    await job_runner.run_once(job.id)
    gateway.generate_link_token.assert_not_awaited()


async def test_manual_recovery_does_not_start_an_automatic_retry_loop(db, lost_token):
    _, link, job = lost_token
    await queue_token_callback_retry(db, link_id=link.id, facility_id=link.facility_id, apply=True)
    await db.commit()
    gateway.generate_link_token.side_effect = RuntimeError("synthetic transport failure")
    await job_runner.run_once(job.id)
    await db.refresh(job)
    assert job.status == "dead" and job.attempts == 2
    assert await job_runner.run_once(job.id) is False
    gateway.generate_link_token.assert_awaited_once()


async def test_crashed_recovery_cannot_consume_another_token_attempt(db, lost_token):
    _, link, job = lost_token
    await queue_token_callback_retry(db, link_id=link.id, facility_id=link.facility_id, apply=True)
    await db.commit()
    claimed = await jobs.claim(db, ident=job.id)
    assert claimed.attempts == 2
    # A lost lease cannot reveal whether NHA accepted the recovery request.
    # Abstain, rather than sending a third generation after a worker crash.
    assert await jobs.claim(db, ident=job.id, now=datetime.now(UTC) + timedelta(minutes=3)) is None
    await db.refresh(job)
    assert job.status == "dead" and job.attempts == 2


@pytest.mark.parametrize("crashed", [False, True])
async def test_initial_token_failure_or_crash_never_automatically_regenerates(
    db, link_case, crashed
):
    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="one-generation"
        )
    )[0]
    ident = jobs.job_id("link_token", link.id)
    await db.commit()
    if crashed:
        assert (await jobs.claim(db, ident=ident)).attempts == 1
        assert (
            await jobs.claim(db, ident=ident, now=datetime.now(UTC) + timedelta(minutes=3)) is None
        )
        gateway.generate_link_token.assert_not_awaited()
    else:
        from app.integrations.abdm.client import AbdmUnavailable

        gateway.generate_link_token.side_effect = AbdmUnavailable(
            "Synthetic timeout", stage="request"
        )
        assert await job_runner.run_once(ident)
        assert await job_runner.run_once(ident) is False
        gateway.generate_link_token.assert_awaited_once()
    db.expire_all()
    row = await db.get(jobs.AbdmJob, ident)
    assert row.status == "dead" and row.attempts == 1


async def test_link_authorization_failure_stops_but_transport_failure_remains_retryable(
    db, link_case
):
    from app.integrations.abdm.client import AbdmAuthError, AbdmUnavailable

    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="link-auth"
        )
    )[0]
    await linking.accept_token(db, link, "synthetic-token", patient.abha_address)
    ident = jobs.job_id("link_context", link.id)
    await db.commit()
    gateway.link_care_contexts.side_effect = AbdmUnavailable(
        "Synthetic outage", status_code=503, stage="request"
    )
    assert await job_runner.run_once(ident)
    row = await db.get(jobs.AbdmJob, ident)
    await db.refresh(row)
    assert row.status == "pending"
    row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    gateway.link_care_contexts.side_effect = AbdmAuthError(
        "Synthetic refusal", status_code=403, stage="request", error_codes=("900908",)
    )
    assert await job_runner.run_once(ident)
    await db.refresh(row)
    assert row.status == "dead" and row.attempts == 2
    assert row.last_error == "AbdmAuthError:request:403:900908"
    assert await job_runner.run_once(ident) is False


async def test_unexpected_link_response_is_not_done_and_is_not_replayed(db, link_case):
    from app.integrations.abdm.client import AbdmProtocolError

    patient, contexts = link_case
    link = (
        await linking.initiate(
            db, patient=patient, context_ids=[contexts[0].id], idempotency_key="link-protocol"
        )
    )[0]
    await linking.accept_token(db, link, "synthetic-token", patient.abha_address)
    ident = jobs.job_id("link_context", link.id)
    await db.commit()
    gateway.link_care_contexts.side_effect = AbdmProtocolError(302)
    assert await job_runner.run_once(ident)
    row = await db.get(jobs.AbdmJob, ident)
    await db.refresh(row)
    assert row.status == "dead" and row.attempts == 1
    assert row.last_error == "AbdmProtocolError:request:302"
    assert await job_runner.run_once(ident) is False
    gateway.link_care_contexts.assert_awaited_once()
    await db.refresh(link)
    assert link.status == "pending", "HTTP delivery must never impersonate the link callback"
