import uuid
import pytest

from app.auth.deps import AuthUser
from tests.pathology.conftest import DOCTOR, LAB_TECH
from fastapi.testclient import TestClient


def test_create_lab_order_item(client_as, seeded_order_id):
    client = client_as(DOCTOR)
    order_id = seeded_order_id
    resp = client.post(
        f"/api/v1/pathology/order-items?order_id={order_id}",
        json={"test_name": "CBC", "sample_type": "blood"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["test_name"] == "CBC"
    assert body["status"] == "placed"
    assert body["accession_number"].startswith("LAB-")
    return body["id"]


def test_wrong_role_cannot_create_order_item(client_as, seeded_order_id):
    unauthorized = AuthUser(sub=str(uuid.uuid4()), username="recept1", roles=["receptionist"])
    client = client_as(unauthorized)
    order_id = seeded_order_id
    resp = client.post(
        f"/api/v1/pathology/order-items?order_id={order_id}",
        json={"test_name": "CBC", "sample_type": "blood"},
    )
    assert resp.status_code == 403


def test_sample_collection_updates_status(client_as, seeded_order_id):
    doc_client = client_as(DOCTOR)
    order_id = seeded_order_id
    created = doc_client.post(
        f"/api/v1/pathology/order-items?order_id={order_id}",
        json={"test_name": "LFT", "sample_type": "blood"},
    ).json()["data"]

    tech_client = client_as(LAB_TECH)
    barcode = f"BC-{uuid.uuid4().hex[:10]}"
    resp = tech_client.put(
        f"/api/v1/pathology/order-items/{created['id']}/sample-collection",
        json={"barcode": barcode},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "in_progress"
    assert body["barcode"] == barcode
    assert body["collected_at"] is not None


def test_duplicate_barcode_rejected(client_as, seeded_order_id):
    doc_client = client_as(DOCTOR)
    tech_client = client_as(LAB_TECH)
    barcode = f"BC-{uuid.uuid4().hex[:10]}"

    # Two items on the SAME order — one order routinely carries several
    # tests, and the barcode uniqueness this asserts is per-sample, not
    # per-order.
    order_id_1 = seeded_order_id
    item1 = doc_client.post(
        f"/api/v1/pathology/order-items?order_id={order_id_1}",
        json={"test_name": "CBC", "sample_type": "blood"},
    ).json()["data"]
    tech_client.put(
        f"/api/v1/pathology/order-items/{item1['id']}/sample-collection",
        json={"barcode": barcode},
    )

    order_id_2 = seeded_order_id
    item2 = doc_client.post(
        f"/api/v1/pathology/order-items?order_id={order_id_2}",
        json={"test_name": "LFT", "sample_type": "blood"},
    ).json()["data"]
    resp = tech_client.put(
        f"/api/v1/pathology/order-items/{item2['id']}/sample-collection",
        json={"barcode": barcode},
    )
    assert resp.status_code == 409


def test_cannot_collect_sample_twice(client_as, seeded_order_id):
    doc_client = client_as(DOCTOR)
    tech_client = client_as(LAB_TECH)
    order_id = seeded_order_id
    item = doc_client.post(
        f"/api/v1/pathology/order-items?order_id={order_id}",
        json={"test_name": "CBC", "sample_type": "blood"},
    ).json()["data"]

    barcode = f"BC-{uuid.uuid4().hex[:10]}"
    first = tech_client.put(
        f"/api/v1/pathology/order-items/{item['id']}/sample-collection",
        json={"barcode": barcode},
    )
    assert first.status_code == 200

    second = tech_client.put(
        f"/api/v1/pathology/order-items/{item['id']}/sample-collection",
        json={"barcode": f"BC-{uuid.uuid4().hex[:10]}"},
    )
    assert second.status_code == 409


def test_list_order_items(client_as, seeded_order_id):
    client = client_as(DOCTOR)
    resp = client.get("/api/v1/pathology/order-items")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "items" in body
    assert "total" in body