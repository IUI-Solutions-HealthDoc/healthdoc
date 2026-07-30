import uuid
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.db import get_db
from app.pharmacy import router as pharmacy_router_module
from app.pharmacy.schemas import DispenseItemOut, PrescriptionQueueResponse
from tests.conftest import FakeResult


def _make_client(fake_session) -> TestClient:
    app = FastAPI()
    app.include_router(pharmacy_router_module.router, prefix="/api/v1")

    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_ping_is_ungated_and_works_without_any_db_calls(fake_session):
    client = _make_client(fake_session)

    resp = client.get("/api/v1/pharmacy/ping")

    assert resp.status_code == 200
    assert resp.json() == {"module": "pharmacy", "status": "ok"}
    assert fake_session.calls == []


def test_queue_endpoint_wired_when_module_enabled(fake_session, monkeypatch):
    # require_module's facility_modules lookup: no row => enabled (default-on)
    fake_session.expect("FROM facility_modules", FakeResult(scalar=None))

    captured = {}

    async def fake_get_queue(db, **kwargs):
        captured.update(kwargs)
        return PrescriptionQueueResponse(items=[], page=1, page_size=20, total=0)

    monkeypatch.setattr(pharmacy_router_module, "get_prescription_queue", fake_get_queue)

    client = _make_client(fake_session)
    resp = client.get("/api/v1/pharmacy/queue")

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}
    assert "facility_id" in captured  # router passed the authenticated user's facility through


def test_dispense_returns_409_when_facility_has_disabled_pharmacy(fake_session):
    # facility_modules row present with is_enabled = False
    fake_session.expect("FROM facility_modules", FakeResult(scalar=False))

    client = _make_client(fake_session)
    resp = client.post(
        "/api/v1/pharmacy/dispenses",
        json={
            "prescription_id": str(uuid.uuid4()),
            "items": [{
                "prescription_item_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "quantity_dispensed": "1",
            }],
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "module_disabled"
    assert resp.json()["detail"]["module"] == "pharmacy"


def test_medicine_search_requires_query_param(fake_session):
    fake_session.expect("FROM facility_modules", FakeResult(scalar=None))

    client = _make_client(fake_session)
    resp = client.get("/api/v1/pharmacy/medicines/search")  # missing required q=

    assert resp.status_code == 422


def test_approve_substitution_endpoint_wired(fake_session, monkeypatch):
    fake_session.expect("FROM facility_modules", FakeResult(scalar=None))

    captured = {}

    async def fake_approve(db, payload, **kwargs):
        captured.update(kwargs)
        return DispenseItemOut(
            item_row_ids=[uuid.uuid4()], prescription_item_id=uuid.uuid4(),
            quantity_dispensed=Decimal("5"), is_substitute=True,
            is_partial=False, approval_status="approved",
        )

    monkeypatch.setattr(pharmacy_router_module, "approve_substitution", fake_approve)

    client = _make_client(fake_session)
    item_id = uuid.uuid4()
    resp = client.post(
        f"/api/v1/pharmacy/dispenses/items/{item_id}/approve",
        json={"approved": True},
    )

    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "approved"
    assert captured["item_row_id"] == item_id
