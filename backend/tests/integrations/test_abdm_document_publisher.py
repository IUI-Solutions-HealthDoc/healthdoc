"""Real clinical service writes must create durable publication work, not just helpers."""

from datetime import timedelta

from sqlalchemy import select

from app.encounters.schemas import EncounterUpdate
from app.encounters.service import update_encounter
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.hip.publisher import publish_encounter
from app.integrations.abdm.jobs import AbdmJob
from app.nursing.models import Vitals
from tests.integrations.test_abdm_document_exports import documents as documents_fixture

documents = documents_fixture


async def test_legacy_reconciliation_is_explicit_and_does_not_invent_visit_scope(db, documents):
    from types import SimpleNamespace

    from app.integrations.abdm.operations import ReconcileIn, reconcile_contexts

    facility, encounters, _, _, context = documents
    expected_document_at = encounters[0].ended_at
    valid = context("encounter", encounters[0].id, "OPConsultation")
    invalid = context("encounter", encounters[1].id, "OPConsultation")
    valid.document_at = invalid.document_at = None
    invalid.reference = f"visit/{encounters[1].visit_id}"
    db.add_all([valid, invalid])
    await db.flush()
    actor = SimpleNamespace(id=encounters[0].provider_user_id, facility_id=facility.id)
    preview = await reconcile_contexts(
        ReconcileIn(context_ids=[valid.id, invalid.id]), actor, db, "preview"
    )
    assert [r.status for r in preview] == ["eligible", "refused"]
    assert valid.document_at is None and invalid.document_at is None
    applied = await reconcile_contexts(
        ReconcileIn(context_ids=[valid.id, invalid.id], apply=True), actor, db, "apply"
    )
    assert [r.status for r in applied] == ["reconciled", "refused"]
    assert valid.document_at == expected_document_at and invalid.document_at is None
    repeated = await reconcile_contexts(
        ReconcileIn(context_ids=[valid.id, invalid.id], apply=True), actor, db, "apply"
    )
    assert repeated == applied
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        await reconcile_contexts(
            ReconcileIn(context_ids=[valid.id], apply=True), actor, db, "apply"
        )
    assert caught.value.status_code == 409


async def test_closing_consultation_publishes_records_and_jobs_atomically(db, documents):
    _, encounters, prescriptions, _, _ = documents
    encounter = encounters[0]
    closed_at = encounter.ended_at
    encounter.ended_at = None
    await db.flush()
    assert (await db.execute(select(AbdmCareContext))).scalars().all() == []
    await update_encounter(
        db, encounter, EncounterUpdate(ended_at=closed_at), actor_id=encounter.created_by
    )
    contexts = (await db.execute(select(AbdmCareContext))).scalars().all()
    assert {c.reference for c in contexts} == {
        f"encounter/{encounter.id}",
        f"prescription/{prescriptions[0].id}",
        f"prescription/{prescriptions[1].id}",
    }
    jobs = (await db.execute(select(AbdmJob))).scalars().all()
    assert {j.target_id for j in jobs} == {c.id for c in contexts}
    assert all(c.created_by == encounter.created_by for c in contexts)
    await publish_encounter(db, encounter, encounter.created_by)
    assert len((await db.execute(select(AbdmJob))).scalars().all()) == 3
    await db.rollback()
    assert (await db.execute(select(AbdmCareContext))).scalars().all() == []
    assert (await db.execute(select(AbdmJob))).scalars().all() == []


async def test_editing_an_open_encounter_does_not_publish(db, documents):
    _, encounters, _, _, _ = documents
    encounter = encounters[0]
    encounter.ended_at = None
    await db.flush()
    await update_encounter(
        db, encounter, EncounterUpdate(plan="Still a draft"), actor_id=encounter.created_by
    )
    assert (await db.execute(select(AbdmJob))).scalars().all() == []


async def test_wellness_context_is_created_only_when_encounter_has_measurements(db, documents):
    import uuid

    _, encounters, _, _, context = documents
    encounter = encounters[0]
    selected = context("wellness", encounter.id, "WellnessRecord")
    db.add(
        Vitals(
            id=uuid.uuid4(),
            patient_id=selected.patient_id,
            encounter_id=encounter.id,
            measured_at=encounter.ended_at - timedelta(minutes=1),
            pulse_bpm=70,
            created_by=encounter.created_by,
        )
    )
    await db.flush()
    await publish_encounter(db, encounter, encounter.created_by)
    assert "WellnessRecord" in (await db.execute(select(AbdmCareContext.hi_type))).scalars().all()
