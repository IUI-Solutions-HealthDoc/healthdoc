"""Cross-encounter referral inbox: scope, closure, filters and pagination."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.orders import service
from app.orders.schemas import ExternalResultCreate
from tests.orders.test_external_results import _external_order, _http_client


async def test_inbox_includes_closed_encounters_and_append_only_result_counts(
    db, seed, encounter, patient, visit
):
    doctor = seed[2]
    order = await _external_order(db, encounter, patient, doctor)
    encounter.ended_at = datetime.now(UTC)
    visit.status = "closed"
    await db.flush()
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        pending = await client.get("/orders/external-referrals")
        assert pending.status_code == 200, pending.text
        row = pending.json()["items"][0]
        assert row["id"] == str(order.id)
        assert row["patient_name"] == patient.full_name
        assert row["patient_identifier"] == patient.uhid
        assert row["result_count"] == 0
        assert row["last_received_at"] is None
        for summary in ["Outside report", "Correction"]:
            await service.record_external_result(
                db,
                order_id=order.id,
                payload=ExternalResultCreate(summary=summary),
                facility_id=doctor.facility_id,
                recorded_by=doctor.id,
            )
        assert (await client.get("/orders/external-referrals")).json()["total"] == 0
        complete = (await client.get("/orders/external-referrals?state=completed")).json()
        assert complete["total"] == 1
        assert complete["items"][0]["result_count"] == 2
        assert complete["items"][0]["last_received_at"] is not None


async def test_inbox_scope_cannot_be_expanded_by_doctor(db, seed, encounter, patient):
    doctor = seed[2]
    own = await _external_order(db, encounter, patient, doctor)
    colleague = await _external_order(db, encounter, patient, doctor)
    colleague.created_by = uuid4()
    internal = await _external_order(db, encounter, patient, doctor)
    internal.fulfilment_mode = "internal"
    await db.flush()
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        result = (await client.get("/orders/external-referrals?all=true&state=all")).json()
        assert result["total"] == 1
        assert [row["id"] for row in result["items"]] == [str(own.id)]
    async with _http_client(db, doctor=doctor, roles=["admin"]) as client:
        result = (await client.get("/orders/external-referrals?state=all")).json()
        assert result["total"] == 2
    moved = SimpleNamespace(
        id=doctor.id,
        keycloak_sub=doctor.keycloak_sub,
        username=doctor.username,
        facility_id=uuid4(),
    )
    async with _http_client(db, doctor=moved, roles=["admin"]) as client:
        result = (await client.get("/orders/external-referrals?state=all")).json()
        assert result["items"] == [] and result["total"] == 0


async def test_inbox_stable_pagination_and_cancelled_filter(db, seed, encounter, patient):
    doctor = seed[2]
    orders = [await _external_order(db, encounter, patient, doctor) for _ in range(3)]
    for order in orders:
        order.ordered_at = datetime(2026, 1, 1, tzinfo=UTC)
    orders[0].status = "cancelled"
    await db.flush()
    async with _http_client(db, doctor=doctor, roles=["doctor"]) as client:
        pages = [
            (await client.get(f"/orders/external-referrals?state=all&limit=1&offset={i}")).json()
            for i in range(4)
        ]
        assert all(page["total"] == 3 and page["limit"] == 1 for page in pages)
        assert [page["offset"] for page in pages] == [0, 1, 2, 3]
        assert [p["items"][0]["id"] for p in pages[:3]] == sorted(
            [str(o.id) for o in orders], reverse=True
        )
        assert pages[3]["items"] == []
        cancelled = (await client.get("/orders/external-referrals?state=cancelled")).json()
        assert [row["id"] for row in cancelled["items"]] == [str(orders[0].id)]
        assert (await client.get("/orders/external-referrals")).json()["total"] == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "state=unknown"])
async def test_inbox_rejects_invalid_query(db, seed, query):
    async with _http_client(db, doctor=seed[2], roles=["doctor"]) as client:
        response = await client.get(f"/orders/external-referrals?{query}")
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", query.split("=")[0]]


@pytest.mark.parametrize("role", ["nurse", "receptionist", "patient", "superadmin"])
async def test_inbox_does_not_expand_existing_worklist_roles(db, seed, role):
    async with _http_client(db, doctor=seed[2], roles=[role]) as client:
        assert (await client.get("/orders/external-referrals")).status_code == 403


@pytest.mark.parametrize(
    "inconsistency", ["patient_facility", "encounter_facility", "visit_facility", "visit_patient"]
)
async def test_inbox_hides_inconsistent_legacy_patient_visit_joins(
    db, seed, encounter, patient, visit, inconsistency
):
    doctor = seed[2]
    await _external_order(db, encounter, patient, doctor)
    if inconsistency == "patient_facility":
        patient.facility_id = uuid4()
    elif inconsistency == "encounter_facility":
        encounter.facility_id = uuid4()
    elif inconsistency == "visit_facility":
        visit.facility_id = uuid4()
    else:
        visit.patient_id = uuid4()
    await db.flush()
    async with _http_client(db, doctor=doctor, roles=["admin"]) as client:
        response = await client.get("/orders/external-referrals?state=all")
        assert response.status_code == 200
        assert response.json()["items"] == [] and response.json()["total"] == 0


async def test_inbox_preserves_thid_for_patient_without_uhid(db, seed, encounter, patient):
    patient.uhid = None
    patient.thid = f"THID-{uuid4().hex[:8]}"
    await _external_order(db, encounter, patient, seed[2])
    async with _http_client(db, doctor=seed[2], roles=["doctor"]) as client:
        response = await client.get("/orders/external-referrals")
        assert response.status_code == 200
        assert response.json()["items"][0]["patient_identifier"] == patient.thid
