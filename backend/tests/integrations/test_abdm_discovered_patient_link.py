"""Linking a chart found by mobile and demographics (USER_INIT_LINK_603-605).

The chart holds no ABHA address, so link-init cannot find it by address. Only
the exact discovery transaction that matched it, from the same asking address,
naming only care contexts that discovery returned, may name it. After a
confirmed, OTP-verified link the chart shows the proven ABHA address and
number (HIP_INIT_NOTIFY_HIECM), unless another chart already holds them.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.audit.models import AuditLog
from app.integrations.abdm import external_router, jobs
from app.integrations.abdm.contracts_v3 import LinkConfirmCallback, LinkInitCallback
from app.integrations.abdm.hip import discovery, gateway, link_otp
from app.integrations.abdm.hip.models import AbdmCareContextLink, AbdmDiscoveryMatch
from app.outbox.models import OutboxEvent
from app.patients.models import Patient
from tests.integrations.test_abdm_deep_link_discovery import (  # noqa: F401
    _discover,
    _dispatchable,
    mobile_only,
)
from tests.integrations.test_abdm_document_exports import documents  # noqa: F401
from tests.integrations.test_abdm_hip_link_operations import callback, link_case  # noqa: F401

pytestmark = pytest.mark.asyncio

ADDRESS = "ravi.new@sbx"


@pytest.fixture
async def discovered(db, mobile_only, monkeypatch):  # noqa: F811
    patient, contexts, facility = mobile_only
    _dispatchable(db, monkeypatch)
    monkeypatch.setattr(link_otp, "issue", AsyncMock(return_value="******3210"))
    monkeypatch.setattr(link_otp, "verify", AsyncMock())
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"synthetic-proof-key" * 2)
    monkeypatch.setattr(gateway, "respond_to_discovery_groups", AsyncMock())
    payload = _discover(verifiedIdentifiers=[
        {"type": "MOBILE", "value": "+91-9876543210"},
        {"type": "ABHA_NUMBER", "value": "91-1111-2222-3333"},
    ])
    await external_router.discover(payload, callback(), db)
    await db.commit()
    return patient, contexts, payload.transaction_id


def _init(transaction_id, patient, contexts, address=ADDRESS):
    return LinkInitCallback.model_validate({
        "transactionId": transaction_id,
        "abhaAddress": address,
        "patient": [{
            "referenceNumber": patient.uhid or str(patient.id),
            "display": patient.full_name,
            "careContexts": [{"referenceNumber": c.reference, "display": c.display} for c in contexts],
            "hiType": contexts[0].hi_type,
            "count": len(contexts),
        }],
    })


async def _link(db, transaction_id):
    return (await db.execute(select(AbdmCareContextLink).where(
        AbdmCareContextLink.transaction_id == transaction_id))).scalar_one()


async def test_discovery_records_what_a_link_init_may_quote(db, discovered):
    patient, contexts, transaction_id = discovered
    match = await db.get(AbdmDiscoveryMatch, discovery.match_id(patient.facility_id, transaction_id))
    assert match.patient_id == patient.id and match.abha_address == ADDRESS
    assert match.abha_number == "91111122223333"
    assert match.care_context_references == sorted(c.reference for c in contexts)
    assert match.matched_by == ["MOBILE"]


async def test_the_exact_discovery_may_start_a_link_with_an_otp_to_the_charts_mobile(
    db, discovered, monkeypatch
):
    from app.integrations.abdm import job_runner

    patient, contexts, transaction_id = discovered
    await external_router.link_init(_init(transaction_id, patient, contexts[:1]), callback(), db)
    link = await _link(db, transaction_id)
    assert link.patient_id == patient.id and link.abha_address == ADDRESS
    assert link.care_context_references == [contexts[0].reference]
    await db.commit()
    ensure, answer = AsyncMock(), AsyncMock()
    monkeypatch.setattr(link_otp, "ensure_issued", ensure)
    monkeypatch.setattr(gateway, "respond_to_link_init", answer)
    reply = (await db.execute(select(jobs.AbdmCallbackReply).where(
        jobs.AbdmCallbackReply.kind == "hip_link_init"))).scalar_one()
    job = (await db.execute(select(jobs.AbdmJob).where(
        jobs.AbdmJob.kind == "callback_ack", jobs.AbdmJob.target_id == reply.id))).scalar_one()
    await job_runner.run_once(job.id)
    await db.refresh(job)
    assert job.status == "done", job.last_error
    assert ensure.await_args.kwargs["mobile"] == "+919876543210"
    answer.assert_awaited_once()


@pytest.mark.parametrize("change", ["address", "transaction", "undiscovered", "expired", "rebound"])
async def test_anything_but_that_discovery_cannot_name_the_chart(db, discovered, change):
    patient, contexts, transaction_id = discovered
    address, selected = ADDRESS, contexts[:1]
    if change == "address":
        address = "someone.else@sbx"
    elif change == "transaction":
        transaction_id = str(uuid.uuid4())
    elif change == "undiscovered":
        selected = [contexts[0].__class__(reference="encounter/" + str(uuid.uuid4()),
                                          display="Not discovered", hi_type=contexts[0].hi_type)]
    elif change == "expired":
        match = await db.get(AbdmDiscoveryMatch, discovery.match_id(patient.facility_id, transaction_id))
        match.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        patient.abha_address = "ravi.other@sbx"
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await external_router.link_init(_init(transaction_id, patient, selected, address), callback(), db)
    assert refused.value.status_code == 404
    assert (await db.execute(select(AbdmCareContextLink).where(
        AbdmCareContextLink.patient_id == patient.id,
        AbdmCareContextLink.abha_address == address))).first() is None


async def test_the_phrs_live_link_init_names_contexts_by_reference_only(db, discovered):
    """phrsbx, 3 Oct 2026: link-init carried no patient or care-context display,
    and requiring one 422'd the link after a successful discovery."""
    patient, contexts, transaction_id = discovered
    payload = LinkInitCallback.model_validate({
        "transactionId": transaction_id,
        "abhaAddress": ADDRESS,
        "patient": [{
            "referenceNumber": patient.uhid or str(patient.id),
            "careContexts": [{"referenceNumber": contexts[0].reference}],
            "hiType": contexts[0].hi_type,
            "count": 1,
        }],
    })
    await external_router.link_init(payload, callback(), db)
    link = await _link(db, transaction_id)
    assert link.care_context_references == [contexts[0].reference]


async def _confirm(db, link):
    payload = LinkConfirmCallback.model_validate(
        {"confirmation": {"linkRefNumber": link.link_ref_number, "token": "123456"}})
    await external_router.link_confirm(payload, callback(), db)


async def test_a_confirmed_link_shows_the_proven_abha_on_the_chart(db, discovered):
    patient, contexts, transaction_id = discovered
    await external_router.link_init(_init(transaction_id, patient, contexts), callback(), db)
    link = await _link(db, transaction_id)
    await _confirm(db, link)
    assert link.status == "confirmed"
    await db.refresh(patient)
    assert patient.abha_address == ADDRESS
    assert patient.abha_number == "91111122223333"
    assert patient.abha_linked_at is not None
    audit = (await db.execute(select(AuditLog).where(
        AuditLog.patient_id == patient.id, AuditLog.resource_type == "patients"))).scalars().all()
    assert any(row.new_value.get("abha_bound_via") == "phr_discovery_link" for row in audit)
    events = (await db.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "abha_linked"))).scalars().all()
    assert [str(e.aggregate_id) for e in events] == [str(patient.id)]


async def test_an_address_another_chart_holds_is_not_copied(db, discovered):
    patient, contexts, transaction_id = discovered
    await external_router.link_init(_init(transaction_id, patient, contexts), callback(), db)
    other = Patient(
        id=uuid.uuid4(), facility_id=patient.facility_id, full_name="Someone Else", sex="male",
        age_years=40, uhid="UHID-OTHER-1", abha_address=ADDRESS, identity_path="demographics_only",
        created_by=patient.created_by,
    )
    db.add(other)
    await db.flush()
    link = await _link(db, transaction_id)
    await _confirm(db, link)
    assert link.status == "confirmed", "the patient proved the OTP; the link stands"
    await db.refresh(patient)
    assert patient.abha_address is None and patient.abha_number is None


async def test_an_address_link_whose_chart_was_unlinked_meanwhile_is_not_rebound(
    db, link_case, monkeypatch  # noqa: F811
):
    """An address-based link-init, then the desk removes the chart's ABHA:
    the PHR's confirmation must not quietly put it back."""
    patient, contexts = link_case
    patient.mobile = "+919876543210"
    monkeypatch.setattr(link_otp, "issue", AsyncMock(return_value="******3210"))
    monkeypatch.setattr(link_otp, "verify", AsyncMock())
    monkeypatch.setattr(link_otp, "_get_hmac_key", lambda: b"synthetic-proof-key" * 2)
    transaction_id = str(uuid.uuid4())
    await external_router.link_init(
        _init(transaction_id, patient, contexts[:1], address=patient.abha_address), callback(), db)
    link = await _link(db, transaction_id)
    patient.abha_address = None
    patient.abha_linked_at = None
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await _confirm(db, link)
    assert refused.value.status_code == 404
    await db.refresh(patient)
    assert patient.abha_address is None


async def test_records_the_address_already_linked_are_not_offered_again(
    db, link_case, monkeypatch  # noqa: F811
):
    """phrsbx, 3 Oct 2026: discovery listed a record the address had already
    linked beside a new one, and the PHR's link then timed out at NHA."""
    from app.integrations.abdm import callback_replies
    from app.integrations.abdm.contracts_v3 import DiscoverCallback

    patient, contexts = link_case
    db.add(AbdmCareContextLink(
        id=uuid.uuid4(), facility_id=patient.facility_id, patient_id=patient.id,
        abha_address=patient.abha_address, status="confirmed",
        care_context_references=[contexts[0].reference],
    ))
    db.add(AbdmCareContextLink(
        id=uuid.uuid4(), facility_id=patient.facility_id, patient_id=patient.id,
        abha_address=patient.abha_address, status="failed",
        care_context_references=[contexts[1].reference],
    ))
    await db.flush()
    schedule = AsyncMock()
    monkeypatch.setattr(callback_replies, "schedule", schedule)
    payload = DiscoverCallback.model_validate({"transactionId": str(uuid.uuid4()), "patient": {
        "id": patient.abha_address, "name": patient.full_name, "gender": "M", "yearOfBirth": 1990,
        "verifiedIdentifiers": [], "unverifiedIdentifiers": None,
    }})
    await external_router.discover(payload, callback(), db)
    wire = schedule.await_args.kwargs["response_data"]["wire"]
    offered = {c["referenceNumber"] for g in wire["patient_groups"] for c in g["careContexts"]}
    assert offered == {contexts[1].reference}, "a failed link is no link; a confirmed one is"
    assert schedule.await_args.kwargs["subject_ids"] == [contexts[1].reference]
