"""tests/integration/test_opd_journey.py

#243 (BB-W7-01) — OPD core journey:
registration -> consultation -> order -> result -> invoice -> payment.

Drives real HTTP endpoints in sequence against real Postgres, carrying
state (visit_id, encounter_id, order_id, invoice_id...) from one step to
the next — the thing a unit test structurally cannot do, and the layer
your lead flagged as the one that would have caught today's 5 production
bugs (queue allocator rollback, NOT NULL columns with no seed, THID
sequence recovery inside an aborted transaction).

All routes are mounted under /api/v1 (confirmed via
`python -c "from app.main import app; [print(r.path) for r in app.routes]"`)
— every URL below reflects that real prefix, not a guess.

ASSUMPTION FLAGGED: app/billing/schemas.py wasn't available when this was
written, so InvoiceBuildResponse's exact field name for the created
invoice id is guessed as `invoice_id` below (marked inline). Confirm
against the real schema before relying on this passing.

CURRENTLY XFAIL — two real schema bugs found via this test:
(1) visit_number_counters table missing entirely — used by
    app/opd/visit_number.py, never created by any migration (0001-0034
    checked via git grep, zero matches). Hit first, on every POST /visits.
(2) idempotency_keys.updated_at missing from migration 0003a (model
    expects it via Timestamps mixin, DB doesn't have it) — would be hit
    on Idempotency-Key replay once (1) is fixed.
Both owned by B1 — see conversation with lead.
"""
from __future__ import annotations

import uuid

import pytest

from tests.integration.conftest import (
    DOCTOR,
    LAB_TECH,
    PATHOLOGIST,
    RECEPTIONIST,
    TEST_DEPARTMENT_ID,
    TEST_FACILITY_ID,
)


class TestOPDCoreJourney:
    @pytest.mark.xfail(
        reason="Blocked on two real schema bugs found via this test: "
               "(1) visit_number_counters table missing entirely — used by "
               "app/opd/visit_number.py, never created by any migration "
               "(0001-0034 checked via git grep, zero matches). This is hit "
               "first, on every call to POST /visits. "
               "(2) idempotency_keys.updated_at missing from migration 0003a "
               "(model expects it via Timestamps mixin, DB doesn't have it) — "
               "would be hit on Idempotency-Key replay once (1) is fixed. "
               "Both owned by B1 — see conversation with lead.",
        strict=False,
    )
    def test_full_opd_journey_registration_to_payment(self, client_as, seeded_patient_id):
        patient_id = seeded_patient_id

        # --- Step 1: registration (opd/router.py -> POST /api/v1/visits) ---
        client = client_as(RECEPTIONIST)
        visit_resp = client.post(
            "/api/v1/visits",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "patient_id": patient_id,
                "created_by": str(uuid.uuid5(uuid.NAMESPACE_OID, RECEPTIONIST.sub)),
                "facility_id": str(TEST_FACILITY_ID),
                "department_id": str(TEST_DEPARTMENT_ID),
                "visit_type": "opd",
                "visit_date": "2026-08-12T09:00:00Z",
            },
        )
        assert visit_resp.status_code == 201, visit_resp.text
        visit = visit_resp.json()
        visit_id = visit["id"]
        assert visit["status"] in ("registered", "waiting")

        same_key = str(uuid.uuid4())
        first = client.post(
            "/api/v1/visits", headers={"Idempotency-Key": same_key},
            json={
                "patient_id": patient_id,
                "created_by": str(uuid.uuid5(uuid.NAMESPACE_OID, RECEPTIONIST.sub)),
                "facility_id": str(TEST_FACILITY_ID),
                "department_id": str(TEST_DEPARTMENT_ID),
                "visit_type": "opd",
                "visit_date": "2026-08-12T09:05:00Z",
            },
        )
        second = client.post(
            "/api/v1/visits", headers={"Idempotency-Key": same_key},
            json={
                "patient_id": patient_id,
                "created_by": str(uuid.uuid5(uuid.NAMESPACE_OID, RECEPTIONIST.sub)),
                "facility_id": str(TEST_FACILITY_ID),
                "department_id": str(TEST_DEPARTMENT_ID),
                "visit_type": "opd",
                "visit_date": "2026-08-12T09:05:00Z",
            },
        )
        assert first.json()["id"] == second.json()["id"], (
            "Idempotency-Key replay failed — a retried registration created "
            "a second visit instead of returning the stored response."
        )

        # --- Step 2: consultation (encounters/router.py -> POST /api/v1/encounters) ---
        client = client_as(DOCTOR)
        doctor_id = str(uuid.uuid5(uuid.NAMESPACE_OID, DOCTOR.sub))
        encounter_resp = client.post(
            "/api/v1/encounters",
            json={
                "visit_id": visit_id,
                "provider_user_id": doctor_id,
                "created_by": doctor_id,
                "encounter_type": "opd_consult",
                "chief_complaint": "Journey test complaint",
            },
        )
        assert encounter_resp.status_code == 201, encounter_resp.text
        encounter = encounter_resp.json()
        encounter_id = encounter["id"]

        # --- Step 3: order (orders/router.py -> POST /api/v1/orders) ---
        order_resp = client.post(
            "/api/v1/orders",
            json={
                "encounter_id": encounter_id,
                "patient_id": patient_id,
                "created_by": doctor_id,
                "order_type": "lab",
                "priority": "routine",
            },
        )
        assert order_resp.status_code == 201, order_resp.text
        order = order_resp.json()
        order_id = order["id"]
        assert order["status"] not in (None, "")

        # --- Step 4a: lab order item (pathology/router.py) ---
        client = client_as(LAB_TECH)
        item_resp = client.post(
            f"/api/v1/pathology/order-items?order_id={order_id}",
            json={
                "test_code": "CBC",
                "test_name": "Complete Blood Count",
                "sample_type": "blood",
            },
        )
        assert item_resp.status_code == 201, item_resp.text
        lab_item_id = item_resp.json()["id"]

        collect_resp = client.put(
            f"/api/v1/pathology/order-items/{lab_item_id}/sample-collection",
            json={"barcode": f"OPDJ-{uuid.uuid4().hex[:10]}"},
        )
        assert collect_resp.status_code == 200, collect_resp.text

        # --- Step 4b: result entry + pathologist verify ---
        result_resp = client.post(
            f"/api/v1/pathology/order-items/{lab_item_id}/results",
            json={"result_data": {"hemoglobin_g_dl": 13.5}, "remarks": "Journey test result"},
        )
        assert result_resp.status_code == 201, result_resp.text

        client = client_as(PATHOLOGIST)
        verify_resp = client.put(
            f"/api/v1/pathology/order-items/{lab_item_id}/results/verify",
            json={},
        )
        assert verify_resp.status_code == 200, verify_resp.text
        assert verify_resp.json()["status"] == "final"

        # --- Step 5: invoice (billing/router.py) ---
        client = client_as(RECEPTIONIST)
        build_resp = client.post(
            f"/api/v1/billing/visits/{visit_id}/invoice/build",
            json={"dry_run": False},
        )
        assert build_resp.status_code == 200, build_resp.text
        build_body = build_resp.json()
        invoice_id = build_body.get("invoice_id") or build_body.get("id")
        assert invoice_id is not None, (
            f"Could not find invoice id on InvoiceBuildResponse: {build_body}"
        )

        # --- Step 6: payment (billing/router.py) ---
        payment_resp = client.post(
            f"/api/v1/billing/invoices/{invoice_id}/payments",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"amount": "0.01", "mode": "cash"},
        )
        assert payment_resp.status_code in (201, 409), payment_resp.text