"""Nurse task queue and incident register defects from the October 2026 QA round.

- The Patient column showed "-": the queue never carried the patient.
- An incident dated in the future reached 0046's CHECK and answered 500.
- An incident naming another facility's patient failed its FK as a 500.
"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.nursing import router as nursing_router
from app.nursing.schemas import IncidentReport
from app.orders.models import Order
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _setup(db):
    facility = Facility(id=uuid.uuid4(), name="Ward DH", code=f"W{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    await db.flush()
    nurse = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                 username=f"n-{uuid.uuid4().hex[:8]}", full_name="Nurse", is_active=True)
    db.add(nurse)
    await db.flush()
    patient = Patient(id=uuid.uuid4(), facility_id=facility.id, uhid="IN-DL-W-2026-000001-1",
                      full_name="Asha Devi", sex="female", age_years=52, status="active",
                      identity_path="demographics_only", created_by=nurse.id)
    db.add(patient)
    await db.flush()
    return facility, nurse, patient


def _report(**extra):
    return {"incident_type": "patient_fall", "severity": "no_harm", "description": "Slipped near bed 4",
            "immediate_action": "Assessed, no injury", "occurred_at": datetime.now(UTC) - timedelta(hours=1),
            **extra}


async def test_the_task_queue_names_the_patient(db):
    facility, nurse, patient = await _setup(db)
    order = Order(id=uuid.uuid4(), order_number=f"ORD-{uuid.uuid4().hex[:8]}", encounter_id=uuid.uuid4(),
                  patient_id=patient.id, facility_id=facility.id, order_type="procedure",
                  priority="routine", status="placed", ordered_at=datetime.now(UTC), created_by=nurse.id)
    db.add(order)
    await db.flush()
    user = SimpleNamespace(id=nurse.id, facility_id=facility.id)
    rows = await nursing_router.list_pending_tasks(current_db_user=user, patient_id=None, order_type=None, db=db)
    assert [(r.order_number, r.patient_name, r.patient_uhid, r.patient_age_years) for r in rows] == [
        (order.order_number, "Asha Devi", patient.uhid, 52)]
    accepted = await nursing_router.accept_task(order.id, current_db_user=user, db=db)
    assert accepted.status == "accepted" and accepted.patient_name == "Asha Devi"


def test_an_incident_cannot_have_happened_in_the_future():
    with pytest.raises(ValidationError, match="cannot be in the future"):
        IncidentReport(**_report(occurred_at=datetime.now(UTC) + timedelta(days=2)))
    # A few minutes of clock drift on a ward PC is not "the future".
    IncidentReport(**_report(occurred_at=datetime.now(UTC) + timedelta(minutes=2)))


def test_numbers_only_text_is_still_a_valid_report():
    report = IncidentReport(**_report(description="12345", immediate_action="67890"))
    assert report.description == "12345"


async def test_an_incident_for_another_facilitys_patient_is_not_found(db):
    facility, nurse, _ = await _setup(db)
    _, _, foreign = await _setup(db)
    user = SimpleNamespace(id=nurse.id, facility_id=facility.id)
    with pytest.raises(HTTPException) as refused:
        await nursing_router.report_incident(IncidentReport(**_report(patient_id=foreign.id)),
                                             current_db_user=user, db=db)
    assert refused.value.status_code == 404


async def test_an_incident_is_recorded(db):
    facility, nurse, patient = await _setup(db)
    user = SimpleNamespace(id=nurse.id, facility_id=facility.id)
    out = await nursing_router.report_incident(IncidentReport(**_report(patient_id=patient.id)),
                                               current_db_user=user, db=db)
    assert out.status == "reported" and out.patient_id == patient.id
