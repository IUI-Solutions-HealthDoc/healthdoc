"""Worklists name the patient (QA 10-12 Oct 2026, BUG-09 / D-01).

The lab and radiology worklists showed no patient and the dispense screen
only an internal id, so nobody at the bench could check whose sample, scan or
medicine it was. Rows now carry name, UHID, age and sex, from the caller's
facility only.
"""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.common.patient_brief import patient_briefs
from app.orders.models import Order
from app.pathology import router as lab_router
from app.pathology.models import LabOrderItem
from app.patients.models import Patient
from app.radiology import router as rad_router
from app.radiology.models import RadiologyOrderItem
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _world(db):
    facility = Facility(id=uuid.uuid4(), name="DH", code=f"L{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    await db.flush()
    user = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                username=f"u-{uuid.uuid4().hex[:8]}", full_name="Tech", is_active=True)
    db.add(user)
    await db.flush()
    patient = Patient(id=uuid.uuid4(), facility_id=facility.id, uhid=f"UH-{uuid.uuid4().hex[:6]}",
                      full_name="Child Kumar", sex="male", age_years=3, status="active",
                      identity_path="demographics_only", created_by=user.id)
    db.add(patient)
    await db.flush()
    return facility, user, patient


async def _order(db, facility, user, patient, order_type):
    order = Order(id=uuid.uuid4(), order_number=f"O-{uuid.uuid4().hex[:8]}", encounter_id=uuid.uuid4(),
                  patient_id=patient.id, facility_id=facility.id, order_type=order_type, priority="routine",
                  status="placed", ordered_at=datetime.now(UTC), created_by=user.id)
    db.add(order)
    await db.flush()
    return order


async def test_the_lab_worklist_names_the_patient(db):
    facility, user, patient = await _world(db)
    order = await _order(db, facility, user, patient, "lab")
    db.add(LabOrderItem(id=uuid.uuid4(), order_id=order.id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
                        test_name="CBC", sample_type="blood", status="placed",
                        specimen_status="pending_collection", created_by=user.id))
    await db.flush()
    page = await lab_router.list_lab_order_items(
        current_db_user=SimpleNamespace(id=user.id, facility_id=facility.id),
        page=1, page_size=20, status=None, db=db)
    assert [(i.patient_name, i.patient_uhid, i.patient_age_years) for i in page.items] == [
        ("Child Kumar", patient.uhid, 3)]


async def test_the_radiology_worklist_names_the_patient(db):
    facility, user, patient = await _world(db)
    order = await _order(db, facility, user, patient, "radiology")
    db.add(RadiologyOrderItem(id=uuid.uuid4(), order_id=order.id, accession_number=f"RAD-{uuid.uuid4().hex[:8]}",
                              modality="xray", scan_type="Chest PA", status="placed", created_by=user.id))
    await db.flush()
    page = await rad_router.list_radiology_order_items(
        current_db_user=SimpleNamespace(id=user.id, facility_id=facility.id),
        page=1, page_size=20, status=None, db=db, current_user=None)
    assert [i.patient_name for i in page.items] == ["Child Kumar"]


async def test_another_facilitys_patient_is_never_named(db):
    facility, _, _ = await _world(db)
    _, _, foreign = await _world(db)
    assert await patient_briefs(db, [foreign.id], facility.id) == {}
