"""Automated tests for Suite 6: Critical Alerts, LIS Specimen Tracking, PACS Attachments, and Pharmacy Returns (HD-21 to HD-24)."""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.deps import DbUser
from app.inventory.models import InventoryBatch, InventoryItem, StockLocation
from app.orders.models import Order
from app.pathology.analyte_service import evaluate_result_analytes
from app.pathology.models import CriticalAlert, LabAnalyte, LabOrderItem, LabResult, LabSpecimenEvent
from app.pathology.schemas import (
    CriticalAlertAcknowledgeRequest,
    SpecimenCollectRequest,
    SpecimenRejectRequest,
)
from app.pathology.router import (
    acknowledge_critical_alert,
    list_critical_alerts,
    list_specimen_events,
    specimen_collect,
    specimen_receive,
    specimen_recollect,
    specimen_reject,
)
from app.pharmacy.models import PharmacyReturn
from app.pharmacy.schemas import PharmacyReturnCreate
from app.pharmacy.service import create_pharmacy_return, list_pharmacy_returns
from app.radiology.models import RadiologyAttachment, RadiologyOrderItem
from app.radiology.router import list_order_attachments, upload_order_attachment
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _setup_suite_6_environment(db):
    facility = Facility(
        id=uuid.uuid4(),
        name="Apex Multi-Specialty Hospital",
        code=f"APEX{uuid.uuid4().hex[:4]}",
        state_code="MH",
    )
    db.add(facility)

    tech_user = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_{uuid.uuid4().hex[:6]}",
        username=f"tech_{uuid.uuid4().hex[:6]}",
        full_name="Alex Technician",
        is_active=True,
    )
    db.add(tech_user)

    doc_user = User(
        id=uuid.uuid4(),
        facility_id=facility.id,
        keycloak_sub=f"sub_{uuid.uuid4().hex[:6]}",
        username=f"doc_{uuid.uuid4().hex[:6]}",
        full_name="Dr. Mehta",
        is_active=True,
    )
    db.add(doc_user)
    await db.flush()

    patient = Patient(
        id=uuid.uuid4(),
        facility_id=facility.id,
        uhid=f"UHID-{uuid.uuid4().hex[:6].upper()}",
        full_name="Rohan Sharma",
        sex="male",
        age_years=40,
        status="active",
        identity_path="demographics_only",
        created_by=doc_user.id,
    )
    db.add(patient)
    await db.flush()

    # Insert order
    order = Order(
        id=uuid.uuid4(),
        order_number=f"ORD-{uuid.uuid4().hex[:10]}",
        encounter_id=uuid.uuid4(),
        facility_id=facility.id,
        patient_id=patient.id,
        order_type="lab",
        priority="routine",
        status="placed",
        ordered_at=datetime.now(timezone.utc),
        created_by=doc_user.id,
    )
    db.add(order)
    await db.flush()

    tech_db_user = DbUser(
        id=tech_user.id,
        facility_id=facility.id,
        keycloak_sub=tech_user.keycloak_sub,
        username=tech_user.username,
        roles=["lab_tech", "pharmacist", "admin"],
    )
    doc_db_user = DbUser(
        id=doc_user.id,
        facility_id=facility.id,
        keycloak_sub=doc_user.keycloak_sub,
        username=doc_user.username,
        roles=["doctor", "radiologist", "admin"],
    )

    return facility, tech_user, doc_user, patient.id, order, tech_db_user, doc_db_user


# ---------------- 1. HD-21: CRITICAL ALERTS & OUTBOX TESTS ----------------


async def test_critical_alert_generation_and_acknowledgement(db):
    facility, tech_user, doc_user, patient_id, order, tech_curr, doc_curr = await _setup_suite_6_environment(db)

    # Add analyte rule with critical bounds
    analyte = LabAnalyte(
        id=uuid.uuid4(),
        test_code="SERUM_POTASSIUM",
        analyte_code="K",
        analyte_name="Potassium",
        value_type="numeric",
        unit="mmol/L",
        reference_low=Decimal("3.5"),
        reference_high=Decimal("5.0"),
        critical_low=Decimal("2.8"),
        critical_high=Decimal("6.2"),
        is_required=True,
        version=1,
    )
    db.add(analyte)
    await db.flush()

    # Evaluate panic high result (e.g. Potassium 6.8)
    evaluated, flagged = await evaluate_result_analytes(db, "SERUM_POTASSIUM", {"K": 6.8})
    assert flagged == ["K"]
    assert evaluated["_has_critical"] is True
    assert evaluated["_analytes"]["K"]["flag"] == "critical_high"

    # Persist critical alert directly in outbox
    alert_id = uuid.uuid4()
    alert = CriticalAlert(
        id=alert_id,
        facility_id=facility.id,
        patient_id=patient_id,
        order_id=order.id,
        test_code="SERUM_POTASSIUM",
        analyte_code="K",
        analyte_name="Potassium",
        value=Decimal("6.8"),
        unit="mmol/L",
        critical_high=Decimal("6.2"),
        severity="critical",
        status="unacknowledged",
    )
    db.add(alert)
    await db.flush()

    # Doctor queries critical alerts
    alert_list = await list_critical_alerts(current_db_user=doc_curr, status="unacknowledged", db=db)
    assert alert_list.total >= 1
    found = next((a for a in alert_list.items if a.id == alert.id), None)
    assert found is not None
    assert found.status == "unacknowledged"
    assert found.value == 6.8

    # Doctor acknowledges alert with note
    ack_res = await acknowledge_critical_alert(
        current_db_user=doc_curr,
        alert_id=alert.id,
        payload=CriticalAlertAcknowledgeRequest(acknowledgement_note="Attending notified, IV calcium gluconate ordered"),
        db=db,
    )
    assert ack_res.status == "acknowledged"
    assert ack_res.acknowledged_by == doc_user.id
    assert "calcium gluconate" in ack_res.acknowledgement_note


# ---------------- 2. HD-22: LIS SPECIMEN REJECTION & RECOLLECTION TESTS ----------------


async def test_specimen_lifecycle_and_recollection(db):
    facility, tech_user, doc_user, patient_id, order, tech_curr, doc_curr = await _setup_suite_6_environment(db)

    item = LabOrderItem(
        id=uuid.uuid4(),
        order_id=order.id,
        accession_number=f"LAB-{uuid.uuid4().hex[:6].upper()}",
        test_code="CBC",
        test_name="Complete Blood Count",
        sample_type="Whole Blood EDTA",
        status="placed",
        specimen_status="pending_collection",
        created_by=tech_user.id,
    )
    db.add(item)
    await db.flush()

    # 1. Collect specimen
    barcode = f"BAR-{uuid.uuid4().hex[:8]}"
    collected_item = await specimen_collect(
        current_db_user=tech_curr,
        item_id=item.id,
        payload=SpecimenCollectRequest(barcode=barcode),
        db=db,
    )
    assert collected_item.specimen_status == "collected"
    assert collected_item.barcode == barcode

    # 2. Receive specimen at lab bench
    received_item = await specimen_receive(
        current_db_user=tech_curr,
        item_id=item.id,
        db=db,
    )
    assert received_item.specimen_status == "received"

    # 3. Reject specimen (e.g. Hemolyzed)
    rejected_item = await specimen_reject(
        current_db_user=tech_curr,
        item_id=item.id,
        payload=SpecimenRejectRequest(rejection_reason="hemolyzed", notes="Gross hemolysis observed"),
        db=db,
    )
    assert rejected_item.specimen_status == "rejected"
    assert rejected_item.rejection_reason == "hemolyzed"

    # 4. Recollect specimen (spawns new linked item with recollected_from_id)
    with patch("app.pathology.router.allocate_accession_number", return_value="LAB-20260919-00001"):
        recollected_item = await specimen_recollect(
            current_db_user=tech_curr,
            item_id=item.id,
            db=db,
        )
    assert recollected_item.recollected_from_id == item.id
    assert recollected_item.specimen_status == "pending_collection"
    assert recollected_item.test_code == "CBC"

    # Verify original item transitioned to recollected
    await db.refresh(item)
    assert item.specimen_status == "recollected"

    # 5. Check specimen audit event stream
    events = await list_specimen_events(current_db_user=tech_curr, item_id=item.id, db=db)
    event_types = [e.event_type for e in events]
    assert "collected" in event_types
    assert "received" in event_types
    assert "rejected" in event_types
    assert "recollected" in event_types


# ---------------- 3. HD-23: PACS & ATTACHMENTS TESTS ----------------


async def test_radiology_attachment_management(db):
    facility, tech_user, doc_user, patient_id, order, tech_curr, doc_curr = await _setup_suite_6_environment(db)

    # Mock MinIO client calls so tests run cleanly in any environment
    with patch("app.radiology.router.get_minio_client") as mock_get_client, \
         patch("app.radiology.router.ensure_bucket") as mock_ensure:
        mock_minio = MagicMock()
        mock_get_client.return_value = mock_minio

        # Synthetic DICOM file bytes (128 preamble + DICM magic bytes)
        dicom_data = b"\x00" * 128 + b"DICM" + b"\x01\x02\x03\x04TestDicomImagePayload"
        checksum = hashlib.sha256(dicom_data).hexdigest()

        class DummyUploadFile:
            filename = "chest_xray.dcm"
            content_type = "application/dicom"

            async def read(self):
                return dicom_data

        att_out = await upload_order_attachment(
            current_db_user=doc_curr,
            order_id=order.id,
            file=DummyUploadFile(),
            db=db,
        )

        assert att_out.file_name == "chest_xray.dcm"
        assert att_out.mime_type == "application/dicom"
        assert att_out.file_size_bytes == len(dicom_data)
        assert att_out.checksum_sha256 == checksum

        # Verify listing
        list_out = await list_order_attachments(current_db_user=doc_curr, order_id=order.id, db=db)
        assert list_out.total >= 1
        assert any(a.id == att_out.id for a in list_out.items)


# ---------------- 4. HD-24: PHARMACY RETURN & DISPOSITION TESTS ----------------


async def test_pharmacy_return_resalable_vs_quarantine(db):
    facility, tech_user, doc_user, patient_id, order, tech_curr, doc_curr = await _setup_suite_6_environment(db)

    # Insert test inventory item
    item_id = uuid.uuid4()
    inv_item = InventoryItem(
        id=item_id,
        name="Paracetamol 500mg Tab",
        item_type="medicine",
        form="tablet",
        is_controlled_drug=False,
        is_active=True,
    )
    db.add(inv_item)

    # Insert test stock location
    loc_id = uuid.uuid4()
    stock_loc = StockLocation(
        id=loc_id,
        facility_id=facility.id,
        name="Central Pharmacy Store",
        location_type="pharmacy",
    )
    db.add(stock_loc)

    # Insert test inventory batch with 50 units
    batch_id = uuid.uuid4()
    batch = InventoryBatch(
        id=batch_id,
        item_id=item_id,
        batch_number="BAT-2026-001",
        expiry_date=date(2027, 12, 31),
        quantity=Decimal("50.00"),
        purchase_rate=Decimal("2.50"),
        issue_rate_mrp=Decimal("5.00"),
        stock_location_id=loc_id,
    )
    db.add(batch)
    await db.flush()

    # Case A: Resalable Return -> increases batch stock from 50 to 60
    return_resalable = await create_pharmacy_return(
        db,
        facility_id=facility.id,
        user_id=tech_user.id,
        payload=PharmacyReturnCreate(
            patient_id=patient_id,
            item_id=item_id,
            batch_id=batch_id,
            quantity=Decimal("10.00"),
            return_reason="Unused blister pack returned after discharge",
            disposition="resalable",
        ),
    )
    assert return_resalable.disposition == "resalable"
    assert return_resalable.quantity == Decimal("10.00")

    # Check batch quantity was updated to 60
    batch_row = (await db.execute(
        select(InventoryBatch.quantity).where(InventoryBatch.id == batch_id)
    )).scalar_one()
    assert batch_row == Decimal("60.00")

    # Case B: Quarantine / Damaged Return -> must NOT add to available stock!
    return_quarantine = await create_pharmacy_return(
        db,
        facility_id=facility.id,
        user_id=tech_user.id,
        payload=PharmacyReturnCreate(
            patient_id=patient_id,
            item_id=item_id,
            batch_id=batch_id,
            quantity=Decimal("5.00"),
            return_reason="Damaged blister foil seal",
            disposition="quarantine",
        ),
    )
    assert return_quarantine.disposition == "quarantine"

    # Batch quantity remains 60.00 (NOT incremented to 65.00)
    batch_row_after = (await db.execute(
        select(InventoryBatch.quantity).where(InventoryBatch.id == batch_id)
    )).scalar_one()
    assert batch_row_after == Decimal("60.00")

    # List returns
    returns_list = await list_pharmacy_returns(db, facility_id=facility.id, disposition="quarantine")
    assert returns_list.total >= 1
    assert any(r.id == return_quarantine.id for r in returns_list.items)


# ---------------- 5. HD-19: ANALYTE VALIDATION EDGE CASES ----------------


async def test_analyte_validation_rejects_non_finite_and_booleans(db):
    facility, tech_user, doc_user, patient_id, order, tech_curr, doc_curr = await _setup_suite_6_environment(db)

    analyte = LabAnalyte(
        id=uuid.uuid4(),
        test_code="TEST_GLUCOSE",
        analyte_code="GLU",
        analyte_name="Glucose",
        value_type="numeric",
        reference_low=Decimal("70"),
        reference_high=Decimal("140"),
        is_required=True,
        version=1,
    )
    db.add(analyte)
    await db.flush()

    # Rejects boolean
    with pytest.raises(ValueError, match="must be numeric, got boolean"):
        await evaluate_result_analytes(db, "TEST_GLUCOSE", {"GLU": True})

    # Rejects NaN
    with pytest.raises(ValueError, match="must contain a finite numeric value"):
        await evaluate_result_analytes(db, "TEST_GLUCOSE", {"GLU": float("nan")})

    # Rejects missing required analyte unconditionally
    with pytest.raises(ValueError, match="Missing required analyte"):
        await evaluate_result_analytes(db, "TEST_GLUCOSE", {"UNRELATED_KEY": "XYZ"})
