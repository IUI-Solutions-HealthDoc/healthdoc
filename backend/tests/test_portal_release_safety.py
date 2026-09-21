import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.opd.models import Encounter, Visit
from app.orders.models import Prescription
from app.patients.portal_self_router import get_my_documents, get_my_document_detail
from tests.test_suite_9_portal_terminology_a11y import suite_9_seed

pytestmark = pytest.mark.asyncio


async def test_unfinished_prescription_is_hidden_from_list_and_guessed_detail(db, suite_9_seed):
    ctx = suite_9_seed
    patient, actor = ctx["patient"], ctx["staff_user"]
    visit = Visit(id=uuid.uuid4(), visit_number="TEST-PORTAL-RELEASE", patient_id=patient.id,
                  facility_id=patient.facility_id, visit_type="opd", visit_date=datetime.now(UTC),
                  created_by=actor.id)
    db.add(visit)
    await db.flush()
    encounter = Encounter(id=uuid.uuid4(), visit_id=visit.id, facility_id=patient.facility_id,
                          provider_user_id=actor.id, encounter_type="consultation", created_by=actor.id)
    db.add(encounter)
    await db.flush()
    prescription = Prescription(id=uuid.uuid4(), encounter_id=encounter.id,
                                patient_id=patient.id, facility_id=patient.facility_id, created_by=actor.id)
    db.add(prescription)
    await db.flush()
    binding, caller = ctx["binding"], ctx["patient_caller"]
    result = await get_my_documents(binding, caller, db, category="prescription", limit=50, offset=0)
    assert result.total == 0
    with pytest.raises(HTTPException) as exc:
        await get_my_document_detail("prescription", prescription.id, binding, caller, db)
    assert exc.value.status_code == 404
    encounter.ended_at = datetime.now(UTC)
    await db.flush()
    result = await get_my_documents(binding, caller, db, category="prescription", limit=50, offset=0)
    assert result.total == 1
    assert result.items[0].id == prescription.id
    detail = await get_my_document_detail("prescription", prescription.id, binding, caller, db)
    assert detail.id == prescription.id
    # An inconsistent encounter/visit association must not be excused by the RX's patient_id.
    visit.patient_id = uuid.uuid4()
    await db.flush()
    assert (await get_my_documents(binding, caller, db, category="prescription", limit=50, offset=0)).total == 0
    with pytest.raises(HTTPException):
        await get_my_document_detail("prescription", prescription.id, binding, caller, db)
