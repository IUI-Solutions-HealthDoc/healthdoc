"""POST /visits and PATCH /visits/{id}/status rules the front desk depends on.

Facility scope of the patient and department, one open visit per patient,
type and department per day, a server-stamped visit date, a receipt that
commits with the visit, reception limited to ending a visit, and a queue
token that ends with it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.billing import service as billing_service
from app.common.db import get_db
from app.common.idempotency_models import IdempotencyKey
from app.departments.models import Department
from app.opd import router as opd_router
from app.opd import service, visit_number
from app.opd.models import Visit
from app.opd.schemas import VisitStatusUpdate
from app.patients.models import Patient
from app.queue import service as queue_service
from app.users.models import Facility


def _patient(facility_id, created_by) -> Patient:
    return Patient(
        id=uuid.uuid4(), uhid=f"UH{uuid.uuid4().hex[:10]}", full_name="Desk Patient", sex="unknown",
        age_years=30, identity_path="demographics_only", facility_id=facility_id, created_by=created_by,
    )


@pytest.fixture(autouse=True)
def no_invoice_or_counter(monkeypatch):
    """The registration invoice needs a tariff and the visit counter is raw
    Postgres SQL; both are covered by the real-PG visit tests. The rules under
    test here sit before them."""
    async def _skip(*args, **kwargs):
        return None

    counter = iter(range(1, 10_000))

    async def _next_sequence(*args, **kwargs):
        return next(counter)

    monkeypatch.setattr(billing_service, "create_registration_invoice", _skip)
    monkeypatch.setattr(visit_number, "next_visit_sequence", _next_sequence)


@pytest.fixture
async def world(db, seed):
    dept, room, actor = seed
    patient = _patient(dept.facility_id, actor.id)
    other_facility = Facility(id=uuid.uuid4(), code="OTH02", name="Other", state_code="TS")
    db.add_all([patient, other_facility])
    await db.flush()
    other_dept = Department(id=uuid.uuid4(), code="OTD", name="Other Dept", facility_id=other_facility.id)
    other_patient = _patient(other_facility.id, actor.id)
    second_dept = Department(id=uuid.uuid4(), code="ORT", name="Ortho", facility_id=dept.facility_id)
    db.add_all([other_dept, other_patient, second_dept])
    await db.flush()
    return {
        "dept": dept, "room": room, "actor": actor, "patient": patient,
        "second_dept": second_dept, "other_dept": other_dept, "other_patient": other_patient,
    }


def _client(db, actor, roles) -> httpx.AsyncClient:
    async def override_db():
        yield db

    app = FastAPI()
    app.include_router(opd_router.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=actor.keycloak_sub, username=actor.username, roles=roles
    )
    app.dependency_overrides[get_current_db_user] = lambda: DbUser(
        id=actor.id, keycloak_sub=actor.keycloak_sub, username=actor.username,
        facility_id=actor.facility_id, roles=roles,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _body(w, **overrides):
    body = {"patient_id": str(w["patient"].id), "department_id": str(w["dept"].id), "visit_type": "opd"}
    body.update(overrides)
    return body


async def _post(client, body, key=None):
    return await client.post("/visits", json=body, headers={"Idempotency-Key": key or str(uuid.uuid4())})


async def test_patient_or_department_from_another_facility_is_not_found(db, world):
    async with _client(db, world["actor"], ["receptionist"]) as client:
        resp = await _post(client, _body(world, patient_id=str(world["other_patient"].id)))
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "patient_not_found"

        resp = await _post(client, _body(world, department_id=str(world["other_dept"].id)))
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "department_not_found"

    assert (await db.execute(select(func.count()).select_from(Visit))).scalar_one() == 0


async def test_second_open_visit_same_type_and_department_returns_the_first(db, world):
    async with _client(db, world["actor"], ["receptionist"]) as client:
        first = await _post(client, _body(world))
        assert first.status_code == 201, first.text

        again = await _post(client, _body(world))
        assert again.status_code == 409
        detail = again.json()["detail"]
        assert detail["code"] == "open_visit_exists"
        assert detail["visit_id"] == first.json()["id"]

        other_department = await _post(client, _body(world, department_id=str(world["second_dept"].id)))
        assert other_department.status_code == 201, "a second department is a second visit"

        other_type = await _post(client, _body(world, visit_type="direct_service"))
        assert other_type.status_code == 201


async def test_a_closed_or_earlier_visit_does_not_block_a_new_one(db, world):
    earlier = Visit(
        id=uuid.uuid4(), visit_number=f"V-{uuid.uuid4().hex[:8]}", patient_id=world["patient"].id,
        facility_id=world["dept"].facility_id, department_id=world["dept"].id, visit_type="opd",
        visit_date=datetime.now(UTC) - timedelta(days=2), created_by=world["actor"].id,
    )
    cancelled_today = Visit(
        id=uuid.uuid4(), visit_number=f"V-{uuid.uuid4().hex[:8]}", patient_id=world["patient"].id,
        facility_id=world["dept"].facility_id, department_id=world["dept"].id, visit_type="opd",
        status="cancelled", visit_date=datetime.now(UTC), created_by=world["actor"].id,
    )
    db.add_all([earlier, cancelled_today])
    await db.flush()

    async with _client(db, world["actor"], ["receptionist"]) as client:
        resp = await _post(client, _body(world))
    assert resp.status_code == 201, resp.text


async def test_the_server_sets_the_visit_date(db, world):
    before = datetime.now(UTC)
    async with _client(db, world["actor"], ["receptionist"]) as client:
        resp = await _post(client, _body(world, visit_date="2001-01-01T09:00:00+05:30"))
    assert resp.status_code == 201, resp.text
    stamped = datetime.fromisoformat(resp.json()["visit_date"])
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    assert stamped >= before - timedelta(seconds=5)


async def test_visit_and_receipt_commit_together_and_a_retry_replays(db, world, monkeypatch):
    commits = 0
    real_commit = db.commit

    async def counting_commit():
        nonlocal commits
        commits += 1
        await real_commit()

    monkeypatch.setattr(db, "commit", counting_commit)
    key = str(uuid.uuid4())
    async with _client(db, world["actor"], ["receptionist"]) as client:
        first = await _post(client, _body(world), key)
        assert first.status_code == 201, first.text
        route_commits = commits
        replay = await _post(client, _body(world), key)

    assert route_commits == 1, "the visit must not be committed before its receipt"
    assert replay.status_code in (200, 201)
    assert replay.json()["id"] == first.json()["id"]
    receipts = (await db.execute(select(func.count()).select_from(IdempotencyKey))).scalar_one()
    assert receipts == 1
    assert (await db.execute(select(func.count()).select_from(Visit))).scalar_one() == 1


async def _visit(db, w, status="registered") -> Visit:
    visit = Visit(
        id=uuid.uuid4(), visit_number=f"V-{uuid.uuid4().hex[:8]}", patient_id=w["patient"].id,
        facility_id=w["dept"].facility_id, department_id=w["dept"].id, visit_type="opd",
        status=status, visit_date=datetime.now(UTC), created_by=w["actor"].id,
    )
    db.add(visit)
    await db.flush()
    return visit


@pytest.mark.parametrize("target", ["in_consultation", "completed", "closed"])
async def test_reception_cannot_move_a_visit_into_clinical_states(db, world, target):
    visit = await _visit(db, world)
    async with _client(db, world["actor"], ["receptionist"]) as client:
        resp = await client.patch(
            f"/visits/{visit.id}/status", json={"status": target},
            headers={"If-Match": str(visit.row_version)},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "visit_status_not_permitted"


async def test_reception_cancel_ends_the_live_queue_token(db, world):
    visit = await _visit(db, world)
    queue = await queue_service.create_queue(
        db, department_id=world["dept"].id, doctor_user_id=world["actor"].id, room_id=world["room"].id,
        display_label="Q", service_date=datetime.now(UTC).date(), caller_facility_id=world["dept"].facility_id,
    )
    token = await queue_service.create_token(
        db, queue_id=queue.id, visit_id=visit.id, priority="normal",
        caller_facility_id=world["dept"].facility_id,
    )
    queue.now_serving_token_id = token.id
    await db.flush()

    async with _client(db, world["actor"], ["receptionist"]) as client:
        resp = await client.patch(
            f"/visits/{visit.id}/status",
            json={"status": "lwbs", "reason": "Left before being called", "updated_by": str(uuid.uuid4())},
            headers={"If-Match": str(visit.row_version)},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "lwbs"
    await db.refresh(token)
    await db.refresh(queue)
    assert token.status == "cancelled"
    assert queue.now_serving_token_id is None


async def test_doctor_keeps_clinical_transitions(db, world):
    visit = await _visit(db, world)
    async with _client(db, world["actor"], ["doctor"]) as client:
        resp = await client.patch(
            f"/visits/{visit.id}/status", json={"status": "in_consultation"},
            headers={"If-Match": str(visit.row_version)},
        )
    assert resp.status_code == 200, resp.text


def test_status_update_no_longer_asks_the_client_for_an_actor():
    assert "updated_by" not in VisitStatusUpdate.model_fields
    VisitStatusUpdate(status="cancelled", reason="duplicate")


async def test_completed_tokens_are_left_alone(db, world):
    visit = await _visit(db, world)
    queue = await queue_service.create_queue(
        db, department_id=world["dept"].id, doctor_user_id=world["actor"].id, room_id=None,
        display_label="Q2", service_date=datetime.now(UTC).date(), caller_facility_id=world["dept"].facility_id,
    )
    token = await queue_service.create_token(
        db, queue_id=queue.id, visit_id=visit.id, priority="normal",
        caller_facility_id=world["dept"].facility_id,
    )
    token.status = "completed"
    await db.flush()

    cancelled = await queue_service.cancel_live_tokens_for_visit(db, visit.id)
    assert cancelled == []
    await db.refresh(token)
    assert token.status == "completed"
