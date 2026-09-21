"""Live PostgreSQL HTTP journey replacing the valid Lab scope from stale PR #397."""

from __future__ import annotations

import asyncio
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.deps import AuthUser
from tests._lab_seed import TEST_DATABASE_URL, seed_order_chain
from tests.pathology.conftest import DOCTOR, LAB_TECH

VERIFYING_TECH = AuthUser(
    sub="lab-journey-verifier-0001",
    username="lab-journey-verifier",
    roles=["lab_tech"],
)


async def _critical_notification_count(item_id: str) -> int:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM notification_history "
                        "WHERE event_type='lab_critical_result' "
                        "AND payload->>'lab_order_item_id'=:item_id"
                    ),
                    {"item_id": item_id},
                )
            ).scalar_one()
    finally:
        await engine.dispose()


def test_lab_order_to_critical_alert_and_dual_verification(client_as):
    order_id = seed_order_chain([DOCTOR.sub, LAB_TECH.sub, VERIFYING_TECH.sub])

    client = client_as(DOCTOR)
    response = client.post(
        f"/api/v1/pathology/order-items?order_id={order_id}",
        json={"test_code": "HB", "test_name": "Hemoglobin", "sample_type": "blood"},
    )
    assert response.status_code == 201, response.text
    item_id = response.json()["data"]["id"]

    client = client_as(LAB_TECH)
    response = client.put(
        f"/api/v1/pathology/order-items/{item_id}/sample-collection",
        json={"barcode": f"LABJRN-{uuid.uuid4().hex[:10]}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "in_progress"

    response = client.post(
        f"/api/v1/pathology/order-items/{item_id}/results",
        json={"result_data": {"hemoglobin_g_dl": 5.2}, "remarks": "Critical low value"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "preliminary"

    duplicate = client.post(
        f"/api/v1/pathology/order-items/{item_id}/results",
        json={"result_data": {"hemoglobin_g_dl": 8.1}},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["message"]["code"] == "sample_not_ready_for_result"

    # Maker-checker: the same authenticated app user cannot verify their own result.
    response = client.put(f"/api/v1/pathology/order-items/{item_id}/results/verify", json={})
    assert response.status_code == 403, response.text

    client = client_as(VERIFYING_TECH)
    response = client.put(f"/api/v1/pathology/order-items/{item_id}/results/verify", json={})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "final"

    response = client.get("/api/v1/pathology/order-items?status=released")
    assert response.status_code == 200, response.text
    assert any(row["id"] == item_id for row in response.json()["data"]["items"])
    # No approved haemoglobin rule is configured, so the result is stored
    # without a critical alert. The retired 7–20 placeholder must not fire.
    assert asyncio.run(_critical_notification_count(item_id)) == 0
