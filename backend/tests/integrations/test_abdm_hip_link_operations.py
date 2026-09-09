import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.abdm import external_router, job_runner, jobs
from app.integrations.abdm.callback_auth import GatewayCallback
from app.integrations.abdm.contracts_v3 import GenericCallback, LinkTokenCallback
from app.integrations.abdm.hip import gateway, linking
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.patients.models import Patient
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


async def test_multitype_linking_keeps_independent_token_and_callback_correlations(db, link_case):
    patient, contexts = link_case
    links = await linking.initiate(
        db, patient=patient, context_ids=[c.id for c in contexts], idempotency_key="two-types"
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
    assert len((await db.execute(select(AbdmCareContextLink))).scalars().all()) == 2


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
