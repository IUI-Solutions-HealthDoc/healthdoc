"""M2 reply outage/commit boundaries use synthetic records and mocked transport."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.common.security import decrypt_pii, encrypt_pii
from app.integrations.abdm import callback_replies, external_router, job_runner, jobs
from app.integrations.abdm.contracts_v3 import DiscoverCallback, ProfileShareCallback
from app.integrations.abdm.hip import gateway, link_otp
from tests.integrations.test_abdm_document_exports import documents as documents_fixture
from tests.integrations.test_abdm_hip_link_operations import link_case as link_case_fixture
from tests.integrations.test_abdm_mediated_link_safety import (
    callback,
    confirmation,
    initiation,
)
from tests.integrations.test_abdm_mediated_link_safety import (
    mediated_case as mediated_fixture,
)

documents, link_case, mediated_case = documents_fixture, link_case_fixture, mediated_fixture


@pytest.fixture
def transports(monkeypatch):
    calls = {}
    for name in [
        "respond_to_discovery_groups",
        "respond_to_link_init",
        "respond_to_link_confirm_error",
        "acknowledge_profile_share",
    ]:
        calls[name] = AsyncMock()
        monkeypatch.setattr(gateway, name, calls[name])
    monkeypatch.setattr(link_otp, "ensure_issued", AsyncMock(return_value="******3210"))
    return calls


async def start(db, case, kind, event=None):
    patient, contexts, link = case
    event = event or callback()
    if kind == "hip_discover":
        payload = DiscoverCallback.model_validate(
            {
                "transactionId": str(uuid.uuid4()),
                "patient": {"id": patient.abha_address},
            }
        )
        route = external_router.discover
    elif kind == "hip_link_init":
        payload, route = initiation(patient, contexts[0], link), external_router.link_init
    elif kind == "hip_profile":
        patient.uhid = "IN-TS-TST01-2026-000001-1"
        await db.flush()
        payload = ProfileShareCallback.model_validate(
            {
                "metaData": {"context": "5"},
                "profile": {
                    "patient": {"abhaAddress": patient.abha_address, "name": patient.full_name}
                },
            }
        )
        route = external_router.profile_share
    else:
        payload, route = confirmation(link), external_router.link_confirm
        link_otp.verify.side_effect = link_otp.LinkOtpInvalid("Incorrect OTP")
    await route(payload, event, db)
    return payload, route, event


@pytest.mark.parametrize(
    "kind,method",
    [
        ("hip_discover", "respond_to_discovery_groups"),
        ("hip_link_init", "respond_to_link_init"),
        ("hip_link_reject", "respond_to_link_confirm_error"),
        ("hip_profile", "acknowledge_profile_share"),
    ],
)
async def test_reply_is_committed_before_network_and_retried_with_frozen_wire(
    db,
    mediated_case,
    transports,
    kind,
    method,
):
    payload, route, event = await start(db, mediated_case, kind)
    for call in transports.values():
        call.assert_not_awaited()
    link_otp.ensure_issued.assert_not_awaited()
    reply = (await db.execute(select(jobs.AbdmCallbackReply))).scalar_one()
    assert reply.kind == kind and reply.response_expires_at is not None
    patient = mediated_case[0]
    assert patient.abha_address.encode() not in reply.response_encrypted
    assert patient.full_name.encode() not in reply.response_encrypted
    snapshot = decrypt_pii(
        reply.response_encrypted,
        associated_data=callback_replies.response_aad(
            reply.id,
            reply.facility_id,
            reply.kind,
        ),
    )
    assert '"otp"' not in snapshot and '"token"' not in snapshot
    await db.commit()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    transports[method].side_effect = RuntimeError("synthetic outage")
    await job_runner.run_once(ack_job.id)
    await db.refresh(ack_job)
    assert ack_job.status == "pending"
    first_wire = transports[method].call_args.kwargs
    # Exact callback replay must not refresh ciphertext, deadline or spend proof.
    encrypted, expiry = reply.response_encrypted, reply.response_expires_at
    await route(payload, event, db)
    assert reply.response_encrypted == encrypted and reply.response_expires_at == expiry
    if kind == "hip_link_reject":
        link_otp.verify.assert_awaited_once()
    ack_job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    transports[method].side_effect = None
    await job_runner.run_once(ack_job.id)
    await db.refresh(ack_job)
    assert ack_job.status == "done"
    assert transports[method].call_args.kwargs == first_wire
    assert first_wire["request_id"] == str(ack_job.id)
    assert (await db.execute(select(jobs.AbdmJob.kind))).scalars().all() == ["callback_ack"]
    # Cleanup removes private snapshot bytes but preserves correlation evidence.
    await job_runner.cleanup_expired_keys()
    await db.refresh(reply)
    assert reply.response_encrypted is None
    await route(payload, event, db)
    assert reply.response_encrypted is None


@pytest.mark.parametrize(
    "kind", ["hip_discover", "hip_link_init", "hip_link_reject", "hip_profile"]
)
async def test_rolled_back_reply_never_dispatches(db, mediated_case, transports, kind):
    await start(db, mediated_case, kind)
    await db.rollback()
    assert (await db.execute(select(jobs.AbdmJob))).scalars().all() == []
    assert (await db.execute(select(jobs.AbdmCallbackReply))).scalars().all() == []
    for call in transports.values():
        call.assert_not_awaited()
    link_otp.ensure_issued.assert_not_awaited()


@pytest.mark.parametrize(
    "kind", ["hip_discover", "hip_link_init", "hip_link_reject", "hip_profile"]
)
async def test_expired_snapshot_is_erased_and_cannot_dispatch(db, mediated_case, transports, kind):
    await start(db, mediated_case, kind)
    reply = (await db.execute(select(jobs.AbdmCallbackReply))).scalar_one()
    reply.response_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    await job_runner.cleanup_expired_keys()
    await job_runner.run_once(ack_job.id)
    await db.refresh(reply)
    await db.refresh(ack_job)
    assert reply.response_encrypted is None and ack_job.status != "done"
    for call in transports.values():
        call.assert_not_awaited()


@pytest.mark.parametrize("change", ["mobile", "expired", "documents"])
async def test_init_rechecks_binding_before_any_sms(db, mediated_case, transports, change):
    await start(db, mediated_case, "hip_link_init")
    patient, contexts, link = mediated_case
    if change == "mobile":
        patient.mobile = "+919876543211"
    elif change == "expired":
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        link.care_context_references = [contexts[1].reference]
    await db.commit()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    await job_runner.run_once(ack_job.id)
    link_otp.ensure_issued.assert_not_awaited()
    transports["respond_to_link_init"].assert_not_awaited()


async def test_new_init_has_a_durable_link_before_delivery(db, mediated_case, transports):
    patient, contexts, old = mediated_case
    payload = initiation(patient, contexts[0], old)
    payload.transaction_id = str(uuid.uuid4())
    event = callback()
    await external_router.link_init(payload, event, db)
    await db.commit()
    link = await db.get(type(old), uuid.uuid5(patient.facility_id, payload.transaction_id))
    assert link and link.status == "pending"
    link_otp.ensure_issued.assert_not_awaited()
    await external_router.link_init(payload, event, db)
    assert len((await db.execute(select(jobs.AbdmJob))).scalars().all()) == 1


async def test_changed_discovery_replay_cannot_rebind_a_reply(db, mediated_case, transports):
    payload, route, event = await start(db, mediated_case, "hip_discover")
    await db.commit()
    payload.patient.id = "other-synthetic@sbx"
    with pytest.raises(HTTPException) as caught:
        await route(payload, event, db)
    assert caught.value.status_code == 409
    transports["respond_to_discovery_groups"].assert_not_awaited()


async def test_discovery_with_no_patient_remains_empty_after_retry(db, mediated_case, transports):
    payload = DiscoverCallback.model_validate(
        {
            "transactionId": str(uuid.uuid4()),
            "patient": {"id": "not-present@sbx"},
        }
    )
    await external_router.discover(payload, callback(), db)
    await db.commit()
    ack_job = (await db.execute(select(jobs.AbdmJob))).scalar_one()
    await job_runner.run_once(ack_job.id)
    assert transports["respond_to_discovery_groups"].call_args.kwargs["patient_groups"] == []


async def test_profile_does_not_guess_a_token_from_missing_or_legacy_uhid(
    db, mediated_case, transports
):
    patient, _, _ = mediated_case
    payload = ProfileShareCallback.model_validate(
        {
            "metaData": {"context": "5"},
            "profile": {
                "patient": {"abhaAddress": patient.abha_address, "name": patient.full_name}
            },
        }
    )
    with pytest.raises(HTTPException) as caught:
        await external_router.profile_share(payload, callback(), db)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "profile_uhid_unavailable"
    transports["acknowledge_profile_share"].assert_not_awaited()


# ------------------------------------------------ Scan-and-Share address (M1)
# The published profile-share body carries address as an object:
# {"line", "district", "state", "pinCode"} (Scan-and-Share collection, 14 Aug 2025).
# The ticket builder read it with attribute access, so any non-empty address
# raised AttributeError and failed the share. The tests above send no address.
@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (
            {"line": " 67 Block Se ", "district": "PUNE", "state": "MAHARASHTRA", "pinCode": "411015"},
            {"line": "67 Block Se", "district": "PUNE", "state": "MAHARASHTRA", "pincode": "411015"},
        ),
        (
            {"line": "Ward 4", "district": None, "state": None, "pinCode": None},
            {"line": "Ward 4", "district": None, "state": None, "pincode": None},
        ),
        (None, None),
        ({"line": "", "district": "   "}, None),
    ],
)
async def test_profile_share_maps_the_published_address_object(
    db, mediated_case, transports, address, expected
):
    from app.integrations.abdm.models import ScanShareTicket

    patient, _, _ = mediated_case
    patient.uhid = "IN-TS-TST01-2026-000001-1"
    await db.flush()
    shared = {"abhaAddress": patient.abha_address, "name": patient.full_name}
    if address is not None:
        shared["address"] = address
    payload = ProfileShareCallback.model_validate(
        {"metaData": {"context": "5"}, "profile": {"patient": shared}}
    )

    await external_router.profile_share(payload, callback(), db)

    ticket = (
        await db.execute(select(ScanShareTicket).where(ScanShareTicket.patient_id == patient.id))
    ).scalar_one()
    assert ticket.profile_data["address"] == expected


def test_shared_address_ignores_anything_that_is_not_an_object():
    assert external_router._shared_address("67 Block Se, Pune") is None
    assert external_router._shared_address(["67 Block Se"]) is None
    assert external_router._shared_address({"line": "x" * 500})["line"] == "x" * 200


async def test_a_snapshot_frozen_with_a_masked_hint_is_sent_with_the_number_nha_accepts(
    db, mediated_case, transports
):
    """3 Oct 2026: NHA refused on-init "******3210" with ABDM-9999 "Invalid
    communication hint"; a reply already queued must not keep repeating it."""
    await start(db, mediated_case, "hip_link_init")
    reply = (await db.execute(select(jobs.AbdmCallbackReply))).scalar_one()
    aad = callback_replies.response_aad(reply.id, reply.facility_id, reply.kind)
    data = json.loads(decrypt_pii(reply.response_encrypted, associated_data=aad))
    data["wire"]["communication_hint"] = "******3210"
    reply.response_encrypted = encrypt_pii(json.dumps(data), associated_data=aad)
    await db.commit()
    await job_runner.run_once((await db.execute(select(jobs.AbdmJob))).scalar_one().id)
    assert transports["respond_to_link_init"].call_args.kwargs["communication_hint"] == "9876543210"
