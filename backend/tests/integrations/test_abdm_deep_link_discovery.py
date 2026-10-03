"""M2 HIP_INIT_NOTIFY_HIECM and USER_INIT_LINK_603.

A patient who registered with name, birth year, gender and mobile but no ABHA
address gets a deep-link SMS from ABDM when a record is ready; their PHR app
then discovers the record here by mobile plus a fuzzy demographic match. Only
an unambiguous match answers, and a chart bound to an ABHA address is found by
that address alone.
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.integrations.abdm import callback_replies, external_router, job_runner, jobs
from app.integrations.abdm.contracts_v3 import DiscoverCallback
from app.integrations.abdm.hip import discovery, gateway
from app.patients.models import Patient
from app.users.models import Facility
from tests.integrations.test_abdm_document_exports import documents  # noqa: F401
from tests.integrations.test_abdm_gateway_calls import stub  # noqa: F401
from tests.integrations.test_abdm_hip_link_operations import callback, link_case  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def mobile_only(db, link_case):  # noqa: F811
    patient, contexts = link_case
    patient.abha_address = None
    patient.abha_linked_at = None
    patient.abha_number = None
    patient.full_name = "Ravi Kumar Sharma"
    patient.mobile = "+919876543210"
    patient.dob = date(1990, 5, 17)
    patient.sex = "male"
    facility = await db.get(Facility, patient.facility_id)
    facility.name = "Synthetic District Hospital"
    await db.flush()
    return patient, contexts, facility


async def _job(db, context):
    ident = await jobs.enqueue(
        db, kind="context_notify", target_id=context.id, facility_id=context.facility_id
    )
    await db.commit()
    return await db.get(jobs.AbdmJob, ident)


# --------------------------------------------------------------- deep link


async def test_a_new_record_for_a_mobile_only_patient_asks_abdm_to_text_them(
    db, mobile_only, monkeypatch
):
    patient, contexts, facility = mobile_only
    sms = AsyncMock()
    monkeypatch.setattr(gateway, "notify_patient_sms", sms)
    job = await _job(db, contexts[0])
    await job_runner.notify_context(job)
    await job_runner.notify_context(job)
    assert sms.await_count == 2
    first, retry = (call.kwargs for call in sms.await_args_list)
    assert first == {
        "mobile": "+919876543210",
        "hip_name": "Synthetic District Hospital",
        "request_id": str(uuid.uuid5(job.id, "sms-notify")),
    }
    assert retry == first, "a retry is the same notification, not a second one"


@pytest.mark.parametrize("change", ["has_abha_address", "no_mobile", "landline", "deleted"])
async def test_no_text_when_the_case_does_not_apply(db, mobile_only, monkeypatch, change):
    patient, contexts, _ = mobile_only
    if change == "has_abha_address":
        patient.abha_address = "ravi@sbx"
    elif change == "no_mobile":
        patient.mobile = None
    elif change == "landline":
        patient.mobile = "+91-11-2345678"
    else:
        from datetime import UTC, datetime

        patient.deleted_at = datetime.now(UTC)
    await db.flush()
    sms = AsyncMock()
    monkeypatch.setattr(gateway, "notify_patient_sms", sms)
    job = await _job(db, contexts[0])
    with pytest.raises(job_runner.DeferredJob):
        await job_runner.notify_context(job)
    sms.assert_not_awaited()


async def test_the_notice_carries_only_the_mobile_and_this_hip(stub, monkeypatch):  # noqa: F811
    monkeypatch.setattr(gateway, "hip_id", lambda: "HIP-TEST")
    await gateway.notify_patient_sms(
        mobile="+919876543210", hip_name="Synthetic District Hospital", request_id="rid-1"
    )
    assert stub.last["path"] == "/api/hiecm/hip/v3/link/patient/links/sms/notify2"
    body = stub.last["json"]
    assert body["requestId"] == "rid-1" and body["timestamp"].endswith("Z")
    assert body["notification"] == {
        "phoneNo": "+91-9876543210",
        "hip": {"name": "Synthetic District Hospital", "id": "HIP-TEST"},
    }


@pytest.mark.parametrize(
    ("raw", "wire"),
    [
        ("+919876543210", "+91-9876543210"),
        ("9876543210", "+91-9876543210"),
        ("+91 98765 43210", "+91-9876543210"),
        ("09876543210", "+91-9876543210"),
    ],
)
def test_phone_spellings_normalise(raw, wire):
    assert gateway.deep_link_phone(raw) == wire


@pytest.mark.parametrize("raw", [None, "", "12345", "+1 415 555 0100", "5876543210"])
def test_a_number_that_is_not_an_indian_mobile_is_refused(raw):
    with pytest.raises(ValueError):
        gateway.deep_link_phone(raw)


# --------------------------------------------------------------- discovery


def _discover(**patient):
    base = {
        "id": "ravi.new@sbx",
        "name": "Ravi Kumar Sharma",
        "gender": "M",
        "yearOfBirth": "1990",
        "verifiedIdentifiers": [{"type": "MOBILE", "value": "+91-9876543210"}],
        "unverifiedIdentifiers": [],
    }
    base.update(patient)
    return DiscoverCallback.model_validate(
        {"transactionId": str(uuid.uuid4()), "patient": base}
    )


async def _reply(db, monkeypatch, payload):
    schedule = AsyncMock()
    monkeypatch.setattr(callback_replies, "schedule", schedule)
    await external_router.discover(payload, callback(), db)
    kwargs = schedule.await_args.kwargs
    return kwargs["target_id"], kwargs["response_data"]["wire"]


async def test_a_mobile_only_patient_is_discovered_by_mobile_and_demographics(
    db, mobile_only, monkeypatch
):
    patient, contexts, _ = mobile_only
    target, wire = await _reply(db, monkeypatch, _discover())
    assert target == patient.id
    assert wire["matched_by"] == ["MOBILE"]
    found = {c["referenceNumber"] for g in wire["patient_groups"] for c in g["careContexts"]}
    assert found == {context.reference for context in contexts}


async def test_the_phrs_live_discover_shape_is_accepted(db, mobile_only, monkeypatch):
    """phrsbx, 3 Oct 2026: yearOfBirth as a number and unverifiedIdentifiers null.
    Both were refused with 422, so the patient's discovery found nothing."""
    patient, contexts, _ = mobile_only
    payload = _discover(yearOfBirth=1990, unverifiedIdentifiers=None)
    assert payload.patient.year_of_birth == "1990"
    assert payload.patient.unverified_identifiers == []
    target, wire = await _reply(db, monkeypatch, payload)
    assert target == patient.id, "the chart is found exactly as with the documented shape"
    found = {c["referenceNumber"] for g in wire["patient_groups"] for c in g["careContexts"]}
    assert found == {context.reference for context in contexts}


@pytest.mark.parametrize(
    "name", ["RAVI KUMAR SHARMA", "Ravi Kumar", "Ravi  Kumar  Sharmaa", "ravi kumar sharma"]
)
async def test_desk_spelling_differences_still_match(db, mobile_only, monkeypatch, name):
    patient, _, _ = mobile_only
    target, _ = await _reply(db, monkeypatch, _discover(name=name))
    assert target == patient.id


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Sunita Devi"},
        {"gender": "F"},
        {"yearOfBirth": "1991"},
        {"verifiedIdentifiers": [{"type": "MOBILE", "value": "+91-9876500000"}]},
        {"verifiedIdentifiers": []},
        {"unverifiedIdentifiers": [{"type": "MOBILE", "value": "+91-9876543210"}],
         "verifiedIdentifiers": []},
    ],
)
async def test_a_mismatch_discovers_nothing(db, mobile_only, monkeypatch, change):
    _, _, _ = mobile_only
    target, wire = await _reply(db, monkeypatch, _discover(**change))
    assert target is None and wire["patient_groups"] == [] and wire["matched_by"] == []


async def test_a_chart_bound_to_another_abha_address_is_not_handed_out(
    db, mobile_only, monkeypatch
):
    patient, _, _ = mobile_only
    patient.abha_address = "ravi.other@sbx"
    await db.flush()
    target, _ = await _reply(db, monkeypatch, _discover())
    assert target is None


async def test_a_chart_holding_a_different_abha_number_is_not_matched(
    db, mobile_only, monkeypatch
):
    patient, _, _ = mobile_only
    patient.abha_number = "91000000000001"
    await db.flush()
    target, _ = await _reply(db, monkeypatch, _discover(verifiedIdentifiers=[
        {"type": "MOBILE", "value": "+91-9876543210"},
        {"type": "ABHA_NUMBER", "value": "91-0000-0000-0002"},
    ]))
    assert target is None
    target, _ = await _reply(db, monkeypatch, _discover(verifiedIdentifiers=[
        {"type": "MOBILE", "value": "+91-9876543210"},
        {"type": "ABHA_NUMBER", "value": "91-0000-0000-0001"},
    ]))
    assert target == patient.id


async def test_two_matching_charts_answer_nothing_unless_a_record_number_narrows(
    db, mobile_only, monkeypatch
):
    patient, _, _ = mobile_only
    patient.uhid = "UHID-RAVI-1"
    twin = Patient(
        id=uuid.uuid4(), facility_id=patient.facility_id, uhid="UHID-RAVI-2",
        full_name="Ravi Kumar Sharma", sex="male", dob=date(1990, 2, 2),
        mobile="+919876543210", identity_path="demographics_only", created_by=patient.created_by,
    )
    db.add(twin)
    await db.flush()
    target, _ = await _reply(db, monkeypatch, _discover())
    assert target is None, "two people share this mobile, name, gender and birth year"
    target, wire = await _reply(db, monkeypatch, _discover(
        unverifiedIdentifiers=[{"type": "MR", "value": "UHID-RAVI-1"}]))
    assert target == patient.id and wire["matched_by"] == ["MOBILE", "MR"]


async def test_an_age_only_registration_matches_within_a_year(db, mobile_only, monkeypatch):
    patient, _, _ = mobile_only
    patient.dob = None
    patient.age_years = date.today().year - 1990
    await db.flush()
    for year, found in (("1989", True), ("1990", True), ("1991", True), ("1993", False)):
        target, _ = await _reply(db, monkeypatch, _discover(yearOfBirth=year))
        assert (target == patient.id) is found, year


async def test_another_facilitys_patient_is_never_discovered(db, mobile_only, monkeypatch):
    patient, _, _ = mobile_only
    elsewhere = Facility(id=uuid.uuid4(), code=f"OT{uuid.uuid4().hex[:6]}", name="Other",
                         state_code="DL")
    db.add(elsewhere)
    await db.flush()
    patient.facility_id = elsewhere.id
    await db.flush()
    target, _ = await _reply(db, monkeypatch, _discover())
    assert target is None


def test_names_match_is_symmetric_and_tolerates_initials_and_case():
    assert discovery.names_match("R K Sharma", "R. K. Sharma")
    assert discovery.names_match("Ravi Kumar Sharma", "ravi kumar")
    assert not discovery.names_match("Ravi Kumar", "Rajesh Verma")
    assert not discovery.names_match("", "Ravi")


async def test_discovery_writes_nothing_to_the_patient(db, mobile_only, monkeypatch):
    patient, _, _ = mobile_only
    await _reply(db, monkeypatch, _discover())
    await db.refresh(patient)
    assert patient.abha_address is None
    stored = (await db.execute(select(Patient.abha_address).where(Patient.id == patient.id))).scalar()
    assert stored is None


def _dispatchable(db, monkeypatch):
    """Let the real reply job run against this session, as the mediated fixture does."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.integrations.abdm.hiu import worker as hiu_worker

    monkeypatch.setattr(
        callback_replies, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        hiu_worker, "get_settings", lambda: SimpleNamespace(abdm_hfr_facility_id="TEST-HFR")
    )


async def test_the_discovery_answer_for_a_mobile_only_chart_is_actually_sent(
    db, mobile_only, monkeypatch
):
    """The committed reply goes through the real dispatcher, which re-checks the
    chart's binding before sending. A chart with no ABHA address must pass."""
    patient, contexts, _ = mobile_only
    _dispatchable(db, monkeypatch)
    answer = AsyncMock()
    monkeypatch.setattr(gateway, "respond_to_discovery_groups", answer)
    await external_router.discover(_discover(), callback(), db)
    await db.commit()
    job = (await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.kind == "callback_ack"))).scalar_one()
    await job_runner.run_once(job.id)
    await db.refresh(job)
    assert job.status == "done", job.last_error
    sent = answer.await_args.kwargs
    assert sent["matched_by"] == ["MOBILE"]
    found = {c["referenceNumber"] for g in sent["patient_groups"] for c in g["careContexts"]}
    assert found == {context.reference for context in contexts}


async def test_a_chart_bound_elsewhere_after_discovery_is_not_answered(
    db, mobile_only, monkeypatch
):
    patient, _, _ = mobile_only
    _dispatchable(db, monkeypatch)
    answer = AsyncMock()
    monkeypatch.setattr(gateway, "respond_to_discovery_groups", answer)
    await external_router.discover(_discover(), callback(), db)
    patient.abha_address = "someone.else@sbx"
    await db.commit()
    job = (await db.execute(select(jobs.AbdmJob).where(jobs.AbdmJob.kind == "callback_ack"))).scalar_one()
    await job_runner.run_once(job.id)
    answer.assert_not_awaited()
