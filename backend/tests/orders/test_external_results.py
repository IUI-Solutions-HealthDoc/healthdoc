"""External-referral results close database-schema section 2 rule 3."""
from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.deps import (
    AuthUser,
    DbUser,
    get_current_db_user,
    get_current_user,
)
from app.common.db import get_db
from app.files.models import FileRecord
from app.orders import service
from app.orders.models import OrderExternalResult
from app.orders.router import router as orders_router
from app.orders.schemas import ExternalResultCreate, OrderCreate
from app.users.models import Facility


async def _external_order(db, encounter, patient, actor):
    order = await service.create_order(
        db,
        OrderCreate(
            encounter_id=encounter.id,
            patient_id=patient.id,
            created_by=actor.id,
            order_type="lab",
        ),
    )
    order.fulfilment_mode = "external_referral"
    await db.flush()
    return order


async def test_first_external_result_completes_order_and_writes_audit(
    db, seed, encounter, patient
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)

    result = await service.record_external_result(
        db,
        order_id=order.id,
        payload=ExternalResultCreate(
            provider_name="District Diagnostic Centre",
            summary="Haemoglobin 12.1 g/dL; outside report reviewed.",
            observed_on=date.today(),
        ),
        facility_id=order.facility_id,
        recorded_by=doctor.id,
    )

    assert result.order_id == order.id
    assert result.recorded_by == doctor.id
    assert order.status == "completed"
    assert order.completed_by == doctor.id
    assert order.completed_at is not None
    assert order.accepted_by == doctor.id
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "order_external_results",
                AuditLog.resource_id == result.id,
            )
        )
    ).scalar_one()
    assert audit.patient_id == patient.id
    assert audit.user_id == doctor.id


async def test_correction_appends_and_preserves_first_completion_actor(
    db, seed, encounter, patient
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    first = await service.record_external_result(
        db,
        order_id=order.id,
        payload=ExternalResultCreate(summary="Initial outside result"),
        facility_id=order.facility_id,
        recorded_by=doctor.id,
    )
    first_completed_at = order.completed_at

    correction = await service.record_external_result(
        db,
        order_id=order.id,
        payload=ExternalResultCreate(summary="Corrected outside result"),
        facility_id=order.facility_id,
        recorded_by=doctor.id,
    )
    history = await service.list_external_results(
        db, order_id=order.id, facility_id=order.facility_id
    )

    assert [row.id for row in history] == [first.id, correction.id]
    assert [row.summary for row in history] == [
        "Initial outside result",
        "Corrected outside result",
    ]
    assert order.completed_at == first_completed_at
    assert order.completed_by == doctor.id


@pytest.mark.parametrize(
    ("fulfilment_mode", "status", "expected_code"),
    [
        ("internal", "placed", "order_not_external_referral"),
        ("external_referral", "cancelled", "order_cancelled"),
    ],
)
async def test_external_result_rejects_internal_or_cancelled_order(
    db, seed, encounter, patient, fulfilment_mode, status, expected_code
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    order.fulfilment_mode = fulfilment_mode
    order.status = status
    await db.flush()

    with pytest.raises(service.ExternalResultConflict) as exc_info:
        await service.record_external_result(
            db,
            order_id=order.id,
            payload=ExternalResultCreate(summary="Must not be accepted"),
            facility_id=order.facility_id,
            recorded_by=doctor.id,
        )
    assert exc_info.value.code == expected_code


async def test_external_result_is_non_disclosing_across_facilities(
    db, seed, encounter, patient
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)

    with pytest.raises(service.ExternalResultOrderNotFound):
        await service.record_external_result(
            db,
            order_id=order.id,
            payload=ExternalResultCreate(summary="Cross-facility attempt"),
            facility_id=uuid.uuid4(),
            recorded_by=doctor.id,
        )
    with pytest.raises(service.ExternalResultOrderNotFound):
        await service.list_external_results(
            db, order_id=order.id, facility_id=uuid.uuid4()
        )


async def test_external_result_file_must_belong_to_order_patient_and_facility(
    db, seed, encounter, patient
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    wrong_patient_file = FileRecord(
        id=uuid.uuid4(),
        bucket="hd-files",
        object_key=f"test/{uuid.uuid4()}.pdf",
        original_name="outside.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        owner_module="orders",
        facility_id=order.facility_id,
        patient_id=uuid.uuid4(),
        uploaded_by=doctor.id,
        sensitivity="sensitive",
        scan_status="skipped",
    )
    db.add(wrong_patient_file)
    await db.flush()

    with pytest.raises(service.ExternalResultFileInvalid) as exc_info:
        await service.record_external_result(
            db,
            order_id=order.id,
            payload=ExternalResultCreate(
                summary="Wrong attachment", result_file_id=wrong_patient_file.id
            ),
            facility_id=order.facility_id,
            recorded_by=doctor.id,
        )
    assert exc_info.value.code == "result_file_not_for_order_patient"


async def test_external_result_model_has_no_mutation_service():
    """Corrections are new rows; application code exposes no rewrite primitive."""
    assert not hasattr(service, "update_external_result")
    assert not hasattr(service, "delete_external_result")
    assert OrderExternalResult.__tablename__ == "order_external_results"


def _http_client(db, *, doctor, roles: list[str]) -> httpx.AsyncClient:
    async def override_db():
        yield db

    app = FastAPI()
    app.include_router(orders_router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=doctor.keycloak_sub, username=doctor.username, roles=roles
    )
    app.dependency_overrides[get_current_db_user] = lambda: DbUser(
        id=doctor.id,
        keycloak_sub=doctor.keycloak_sub,
        username=doctor.username,
        facility_id=doctor.facility_id,
        roles=roles,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_external_result_endpoint_enforces_roles(db, seed, encounter, patient):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    async with _http_client(db, doctor=doctor, roles=["billing"]) as client:
        response = await client.post(
            f"/orders/{order.id}/external-results",
            headers={"Idempotency-Key": "outside-result-role-test"},
            json={"summary": "Should be forbidden"},
        )
    assert response.status_code == 403


async def test_external_result_endpoint_is_idempotent(db, seed, encounter, patient):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    headers = {"Idempotency-Key": "outside-result-retry-test"}
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        first = await client.post(
            f"/orders/{order.id}/external-results",
            headers=headers,
            json={"summary": "Outside result received"},
        )
        retry = await client.post(
            f"/orders/{order.id}/external-results",
            headers=headers,
            json={"summary": "Outside result received"},
        )

    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    history = await service.list_external_results(
        db, order_id=order.id, facility_id=order.facility_id
    )
    assert len(history) == 1


async def test_external_result_replay_rechecks_current_facility(db, seed, encounter, patient):
    from types import SimpleNamespace

    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    headers = {"Idempotency-Key": "moved-external-result"}
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        original = await client.post(f"/orders/{order.id}/external-results", headers=headers,
                                     json={"summary": "Private outside report"})
        assert original.status_code == 201
    moved = SimpleNamespace(id=doctor.id, keycloak_sub=doctor.keycloak_sub,
                            username=doctor.username, facility_id=uuid.uuid4())
    async with _http_client(db, doctor=moved, roles=["doctor"]) as client:
        replay = await client.post(f"/orders/{order.id}/external-results", headers=headers,
                                   json={"summary": "Private outside report"})
    assert replay.status_code == 404
    assert "Private outside report" not in replay.text


@pytest.mark.parametrize("key,status", [(None, 400), (" ", 400), ("x" * 256, 422)])
async def test_external_result_requires_bounded_nonblank_action_key(db, seed, encounter, patient, key, status):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        response = await client.post(f"/orders/{order.id}/external-results",
                                     headers={"Idempotency-Key": key} if key else {},
                                     json={"summary": "No unkeyed write"})
    assert response.status_code == status
    assert await service.list_external_results(db, order_id=order.id, facility_id=doctor.facility_id) == []


async def test_order_reads_expose_external_fulfilment_and_completion(db, seed, encounter, patient):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        read = await client.get(f"/orders/{order.id}")
        assert read.json()["fulfilment_mode"] == "external_referral"
        assert read.json()["completed_at"] is None
        created = await client.post(f"/orders/{order.id}/external-results",
                                    headers={"Idempotency-Key": "readback"}, json={"summary": "Outside report"})
        assert created.status_code == 201
        listed = await client.get("/orders", params={"encounter_id": str(encounter.id)})
        row = next(item for item in listed.json()["items"] if item["id"] == str(order.id))
        assert row["fulfilment_mode"] == "external_referral"
        assert row["status"] == "completed" and row["completed_at"] is not None


async def test_external_result_endpoint_hides_missing_or_cross_facility_file(
    db, seed, encounter, patient
):
    _dept, _room, doctor = seed
    order = await _external_order(db, encounter, patient, doctor)
    other_facility = Facility(
        id=uuid.uuid4(),
        code=f"EXT{uuid.uuid4().hex[:6]}",
        name="Other Facility",
        state_code="TS",
    )
    cross_facility_file = FileRecord(
        id=uuid.uuid4(),
        bucket="hd-files",
        object_key=f"test/{uuid.uuid4()}.pdf",
        original_name="outside.pdf",
        content_type="application/pdf",
        size_bytes=100,
        sha256="b" * 64,
        owner_module="orders",
        facility_id=other_facility.id,
        patient_id=patient.id,
        uploaded_by=doctor.id,
        sensitivity="sensitive",
        scan_status="skipped",
    )
    db.add_all([other_facility, cross_facility_file])
    await db.flush()

    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        missing_response = await client.post(
            f"/orders/{order.id}/external-results",
            headers={"Idempotency-Key": "outside-result-missing-file"},
            json={
                "summary": "Attachment must not disclose tenancy",
                "result_file_id": str(uuid.uuid4()),
            },
        )
        cross_facility_response = await client.post(
            f"/orders/{order.id}/external-results",
            headers={"Idempotency-Key": "outside-result-cross-facility-file"},
            json={
                "summary": "Attachment must not disclose tenancy",
                "result_file_id": str(cross_facility_file.id),
            },
        )

    for response in (missing_response, cross_facility_response):
        assert response.status_code == 404
        assert response.json() == {"detail": "result_file_not_found"}


@pytest.mark.parametrize("erased", [False, True])
async def test_external_result_attachment_receipt_and_erasure_guard(db, seed, encounter, patient, erased):
    from datetime import UTC, datetime

    doctor = seed[2]
    order = await _external_order(db, encounter, patient, doctor)
    attachment = FileRecord(
        id=uuid.uuid4(), bucket="hd-files", object_key=f"test/{uuid.uuid4()}.pdf",
        original_name="outside.pdf", content_type="application/pdf", size_bytes=100,
        sha256="c" * 64, owner_module="orders", facility_id=doctor.facility_id,
        patient_id=patient.id, uploaded_by=doctor.id, sensitivity="sensitive", scan_status="skipped",
    )
    if erased:
        attachment.erased_at = datetime.now(UTC)
        attachment.erasure_reason = "Synthetic erasure test"
        attachment.erased_by = doctor.id
    db.add(attachment)
    await db.flush()
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        payload = {"summary": "Outside report", "result_file_id": str(attachment.id)}
        headers = {"Idempotency-Key": "outside-file-receipt"}
        response = await client.post(f"/orders/{order.id}/external-results", json=payload, headers=headers)
        if erased:
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "result_file_erased"
            assert order.completed_at is None
        else:
            assert response.status_code == 201, response.text
            assert response.json()["result_file_id"] == str(attachment.id)
            retry = await client.post(f"/orders/{order.id}/external-results", json=payload, headers=headers)
            assert retry.status_code == 201 and retry.json()["id"] == response.json()["id"]
            history = (await client.get(f"/orders/{order.id}/external-results")).json()["items"]
            assert len(history) == 1 and history[0]["result_file_id"] == str(attachment.id)
