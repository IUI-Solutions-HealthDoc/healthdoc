from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.auth.deps import DbUser
from app.integrations.abdm.hip.router import CareContextIn, create_care_context
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility, User


async def _seed_scope(db):
    facility_a = Facility(
        id=uuid.uuid4(), code=f"A{uuid.uuid4().hex[:6]}", name="A", state_code="DL"
    )
    facility_b = Facility(
        id=uuid.uuid4(), code=f"B{uuid.uuid4().hex[:6]}", name="B", state_code="DL"
    )
    actor = User(
        id=uuid.uuid4(),
        keycloak_sub=f"scope-{uuid.uuid4()}",
        username=f"scope-{uuid.uuid4().hex[:8]}",
        full_name="Scope Doctor",
        facility_id=facility_a.id,
    )
    patient_a = Patient(
        id=uuid.uuid4(),
        full_name="Patient A",
        sex="unknown",
        age_years=30,
        uhid=f"UHID-{uuid.uuid4().hex[:10]}",
        identity_path="demographics_only",
        facility_id=facility_a.id,
        created_by=actor.id,
    )
    patient_b = Patient(
        id=uuid.uuid4(),
        full_name="Patient B",
        sex="unknown",
        age_years=30,
        uhid=f"UHID-{uuid.uuid4().hex[:10]}",
        identity_path="demographics_only",
        facility_id=facility_b.id,
        created_by=actor.id,
    )
    db.add_all([facility_a, facility_b, actor, patient_a, patient_b])
    await db.flush()
    visit_a = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-{uuid.uuid4().hex[:10]}",
        patient_id=patient_a.id,
        facility_id=facility_a.id,
        visit_type="opd",
        status="completed",
        visit_date=datetime.now(UTC),
        created_by=actor.id,
    )
    visit_b = Visit(
        id=uuid.uuid4(),
        visit_number=f"V-{uuid.uuid4().hex[:10]}",
        patient_id=patient_b.id,
        facility_id=facility_b.id,
        visit_type="opd",
        status="completed",
        visit_date=datetime.now(UTC),
        created_by=actor.id,
    )
    db.add_all([visit_a, visit_b])
    await db.flush()
    caller = DbUser(
        id=actor.id,
        keycloak_sub=actor.keycloak_sub,
        username=actor.username,
        facility_id=facility_a.id,
        roles=["doctor"],
    )
    return caller, patient_a, patient_b, visit_a, visit_b


@pytest.mark.asyncio
async def test_care_context_accepts_only_a_visit_for_the_scoped_patient(db):
    caller, patient_a, _patient_b, visit_a, _visit_b = await _seed_scope(db)
    result = await create_care_context(
        CareContextIn(
            patient_id=patient_a.id,
            visit_id=visit_a.id,
            reference=f"visit-{visit_a.id}",
            display="OP consultation",
            hi_type="OPConsultation",
        ),
        current_db_user=caller,
        idempotency_key="scope-valid",
        db=db,
    )
    assert result.hi_type == "OPConsultation"


@pytest.mark.asyncio
async def test_care_context_hides_another_facility_patient(db):
    caller, _patient_a, patient_b, _visit_a, visit_b = await _seed_scope(db)
    with pytest.raises(HTTPException) as caught:
        await create_care_context(
            CareContextIn(
                patient_id=patient_b.id,
                visit_id=visit_b.id,
                reference=f"visit-{visit_b.id}",
                display="Foreign consultation",
                hi_type="OPConsultation",
            ),
            current_db_user=caller,
            idempotency_key="scope-foreign",
            db=db,
        )
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "patient_not_found"


@pytest.mark.asyncio
async def test_care_context_rejects_unknown_abdm_hi_type_before_insert(db):
    caller, patient_a, _patient_b, visit_a, _visit_b = await _seed_scope(db)
    with pytest.raises(HTTPException) as caught:
        await create_care_context(
            CareContextIn(
                patient_id=patient_a.id,
                visit_id=visit_a.id,
                reference=f"visit-{visit_a.id}",
                display="Unknown record",
                hi_type="ClinicalGuess",
            ),
            current_db_user=caller,
            idempotency_key="scope-type",
            db=db,
        )
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_hi_type"
