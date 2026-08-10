import uuid
import pytest

from tests.radiology.conftest import RADIOLOGIST, RADIOLOGY_TECH, DOCTOR


# RAD_TECH kept as an alias so the test bodies below read unchanged.
RAD_TECH = RADIOLOGY_TECH


def test_create_radiology_order_item(client_as, seeded_order_id):
    client = client_as(DOCTOR)
    order_id = seeded_order_id
    resp = client.post(
        f"/api/v1/radiology/order-items?order_id={order_id}",
        json={"modality": "xray", "scan_type": "Chest X-Ray"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["status"] == "placed"
    assert body["accession_number"].startswith("RAD-")


def test_scan_complete_requires_scheduled_status(client_as, seeded_order_id):
    doc_client = client_as(DOCTOR)
    order_id = seeded_order_id
    item = doc_client.post(
        f"/api/v1/radiology/order-items?order_id={order_id}",
        json={"modality": "xray", "scan_type": "Chest X-Ray"},
    ).json()["data"]

    tech_client = client_as(RAD_TECH)
    resp = tech_client.put(
        f"/api/v1/radiology/order-items/{item['id']}/scan-complete",
        json={},
    )
    assert resp.status_code == 409


def test_draft_and_sign_off_report(client_as, seeded_order_id):
    doc_client = client_as(DOCTOR)
    order_id = seeded_order_id
    item = doc_client.post(
        f"/api/v1/radiology/order-items?order_id={order_id}",
        json={"modality": "xray", "scan_type": "Chest X-Ray"},
    ).json()["data"]

    rad_client = client_as(RADIOLOGIST)
    draft = rad_client.post(
        f"/api/v1/radiology/order-items/{item['id']}/reports",
        json={"findings": "No acute findings.", "impression": "Normal chest X-ray."},
    )
    assert draft.status_code == 201
    assert draft.json()["data"]["status"] == "preliminary"

    signed = rad_client.put(
        f"/api/v1/radiology/order-items/{item['id']}/reports/sign-off",
        json={},
    )
    assert signed.status_code == 200
    body = signed.json()["data"]
    assert body["status"] == "final"
    assert body["version"] == 2
    assert body["tat_minutes"] is not None


def test_list_radiology_order_items(client_as, seeded_order_id):
    client = client_as(DOCTOR)
    resp = client.get("/api/v1/radiology/order-items")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "items" in body
    assert "total" in body
