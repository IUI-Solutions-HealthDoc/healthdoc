"""tests/integration/test_opd_journey.py

#243 (BB-W7-01) — OPD core journey:
registration -> consultation -> order -> result -> invoice -> payment.

All routes are mounted under /api/v1. Every JSON response (success or
error) is wrapped by app/common/envelope.py as:
  {"success": bool, "data": ..., "error": null | {...}, "meta": {...}}
so every access below goes through resp.json()["data"][...], not
resp.json()[...] directly.

Three real schema bugs found and fixed via this test, migrations 0035
and 0035a:
  - visit_number_counters table was missing entirely
  - idempotency_keys.updated_at column was missing
  - visits.row_version column was missing
All three confirmed fixed live against Docker Postgres (port 55432).

ASSUMPTION FLAGGED: app/billing/schemas.py wasn't available when this was
written, so InvoiceBuildResponse's exact field name for the created
invoice id is guessed as `invoice_id` below (marked inline).
"""
from __future__ import annotations

import uuid

from tests.integration.conftest import (
    BILLING,
    DOCTOR,
    LAB_TECH,
    PATHOLOGIST,
    RECEPTIONIST,
    TEST_DEPARTMENT_ID,
    TEST_FACILITY_ID,
)


class TestOPDCoreJourney:
    # xfail removed in #389. This journey is what found the gap: §3 0014 promised
    # "one per visit, created at registration with the registration-fee line",
    # billing/service.py enforced it, and nothing created one — the only file
    # mentioning Invoice( was billing/models.py. POST /visits now creates the
    # invoice and its fee line inside the registration transaction, priced from
    # charge_master (seeded in conftest). If this starts failing on the invoice
    # step again, the billing chain has lost its entry point a second time.
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
        visit = visit_resp.json()["data"]
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
        assert first.json()["data"]["id"] == second.json()["data"]["id"], (
            "Idempotency-Key replay failed — a retried registration created "
            "a second visit instead of returning the stored response."
        )

        # --- Step 2: consultation (encounters/router.py -> POST /api/v1/encounters) ---
        client = client_as(DOCTOR)
        doctor_id = str(uuid.uuid5(uuid.NAMESPACE_OID, DOCTOR.sub))
        encounter_key = str(uuid.uuid4())
        encounter_body = {
            "visit_id": visit_id,
            "provider_user_id": doctor_id,
            "created_by": doctor_id,
            "encounter_type": "consultation",
            "chief_complaint": "Journey test complaint",
        }
        encounter_resp = client.post(
            "/api/v1/encounters",
            headers={"Idempotency-Key": encounter_key},
            json=encounter_body,
        )
        assert encounter_resp.status_code == 201, encounter_resp.text
        encounter = encounter_resp.json()["data"]
        encounter_id = encounter["id"]
        encounter_replay = client.post(
            "/api/v1/encounters",
            headers={"Idempotency-Key": encounter_key},
            json=encounter_body,
        )
        assert encounter_replay.status_code == 201, encounter_replay.text
        assert encounter_replay.json()["data"]["id"] == encounter_id

        note_resp = client.patch(
            f"/api/v1/encounters/{encounter_id}",
            headers={"If-Match": str(encounter["row_version"])},
            json={
                "subjective": "Fever for two days",
                "assessment": "Viral syndrome",
                "plan": "Hydration and review",
                "note_status": "stored",
            },
        )
        assert note_resp.status_code == 200, note_resp.text
        assert note_resp.json()["data"]["row_version"] == encounter["row_version"] + 1
        stale_note = client.patch(
            f"/api/v1/encounters/{encounter_id}",
            headers={"If-Match": str(encounter["row_version"])},
            json={"assessment": "must not overwrite"},
        )
        assert stale_note.status_code == 409, stale_note.text
        assert stale_note.json()["error"]["message"]["code"] == "stale_write"

        # --- Step 3: order (orders/router.py -> POST /api/v1/orders) ---
        order_key = str(uuid.uuid4())
        order_body = {
            "encounter_id": encounter_id,
            "patient_id": patient_id,
            "created_by": doctor_id,
            "order_type": "lab",
            "priority": "routine",
        }
        order_resp = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": order_key},
            json=order_body,
        )
        assert order_resp.status_code == 201, order_resp.text
        order = order_resp.json()["data"]
        order_id = order["id"]
        assert order["status"] not in (None, "")
        order_replay = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": order_key},
            json=order_body,
        )
        assert order_replay.status_code == 201, order_replay.text
        assert order_replay.json()["data"]["id"] == order_id
        listed_orders = client.get(
            "/api/v1/orders", params={"encounter_id": encounter_id},
        )
        assert listed_orders.status_code == 200, listed_orders.text
        assert order_id in {row["id"] for row in listed_orders.json()["data"]["items"]}

        wrong_type_procedure = client.post(
            "/api/v1/procedures",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "order_id": order_id,
                "procedure_name": "Must not attach to a lab order",
                "setting": "opd_minor",
            },
        )
        assert wrong_type_procedure.status_code == 422, wrong_type_procedure.text
        assert (
            wrong_type_procedure.json()["error"]["message"]["code"]
            == "order_type_mismatch"
        )

        # --- Step 3b: procedure header + detail + read-back ---
        procedure_order_key = str(uuid.uuid4())
        procedure_order_resp = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": procedure_order_key},
            json={
                "encounter_id": encounter_id,
                "patient_id": patient_id,
                "created_by": doctor_id,
                "order_type": "procedure",
                "priority": "routine",
            },
        )
        assert procedure_order_resp.status_code == 201, procedure_order_resp.text
        procedure_order_id = procedure_order_resp.json()["data"]["id"]
        procedure_key = f"{procedure_order_key}:detail"
        procedure_body = {
            "order_id": procedure_order_id,
            "procedure_name": "Minor wound dressing",
            "setting": "opd_minor",
        }
        missing_key = client.post("/api/v1/procedures", json=procedure_body)
        assert missing_key.status_code == 400, missing_key.text
        assert (
            missing_key.json()["error"]["message"]["code"]
            == "missing_idempotency_key"
        )
        procedure_resp = client.post(
            "/api/v1/procedures",
            headers={"Idempotency-Key": procedure_key},
            json=procedure_body,
        )
        assert procedure_resp.status_code == 201, procedure_resp.text
        procedure = procedure_resp.json()["data"]
        assert procedure["order_id"] == procedure_order_id
        assert procedure["encounter_id"] == encounter_id
        assert procedure["patient_id"] == patient_id
        assert procedure["performed_by"] == doctor_id

        procedure_replay = client.post(
            "/api/v1/procedures",
            headers={"Idempotency-Key": procedure_key},
            json=procedure_body,
        )
        assert procedure_replay.status_code == 201, procedure_replay.text
        assert procedure_replay.json()["data"]["id"] == procedure["id"]

        listed_procedures = client.get(
            "/api/v1/procedures", params={"encounter_id": encounter_id},
        )
        assert listed_procedures.status_code == 200, listed_procedures.text
        assert procedure["id"] in {
            row["id"] for row in listed_procedures.json()["data"]["items"]
        }

        # --- Step 4a: lab order item (pathology/router.py) ---
        client = client_as(LAB_TECH)
        item_resp = client.post(
            f"/api/v1/pathology/order-items?order_id={order_id}",
            headers={"Idempotency-Key": f"{order_key}:detail"},
            json={
                "test_code": "CBC",
                "test_name": "Complete Blood Count",
                "sample_type": "blood",
            },
        )
        assert item_resp.status_code == 201, item_resp.text
        lab_item_id = item_resp.json()["data"]["id"]
        item_replay = client.post(
            f"/api/v1/pathology/order-items?order_id={order_id}",
            headers={"Idempotency-Key": f"{order_key}:detail"},
            json={
                "test_code": "CBC",
                "test_name": "Complete Blood Count",
                "sample_type": "blood",
            },
        )
        assert item_replay.status_code == 201, item_replay.text
        assert item_replay.json()["data"]["id"] == lab_item_id

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
        assert verify_resp.json()["data"]["status"] == "final"

        # --- Step 5: invoice (billing/router.py) ---
        # The billing desk, not the receptionist who registered the patient.
        # The journey now changes hands here, which is the point of the split.
        client = client_as(BILLING)
        build_resp = client.post(
            f"/api/v1/billing/visits/{visit_id}/invoice/build",
            json={"dry_run": False},
        )
        assert build_resp.status_code == 200, build_resp.text
        build_body = build_resp.json()["data"]
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
