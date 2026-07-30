"""POST /encounters/{id}/close — B3-W4-02 (#201).

Closes an encounter and generates FHIR-shaped stub documents (OPD note
Composition + one MedicationRequest per prescription item) for later
ABDM HIP push. Stubs are stored in Mongo, not pushed anywhere yet.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.db import get_db
from app.common.mongo import get_mongo
from app.opd.models import Encounter, Visit
from app.orders.models import Prescription
from app.encounters.schemas import ClosedEncounterOut
from app.integrations.abdm.fhir.builders import build_opd_note_composition, build_medication_request
from app.audit import service as audit_service

router = APIRouter(prefix="/encounters", tags=["encounters"])


@router.post("/{encounter_id}/close", response_model=ClosedEncounterOut)
async def close_encounter(encounter_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Encounter).where(Encounter.id == encounter_id))
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")
    if encounter.ended_at is not None:
        raise HTTPException(status_code=409, detail="Encounter is already closed")

    # patient_id isn't on Encounter directly — trace through visit_id -> Visit.patient_id
    v = await db.execute(select(Visit).where(Visit.id == encounter.visit_id))
    visit = v.scalar_one_or_none()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found for this encounter")

    encounter.ended_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(encounter)

    resources = [
        build_opd_note_composition(
            encounter_id=encounter.id,
            patient_id=visit.patient_id,
            subjective=encounter.subjective,
            objective=encounter.objective,
            assessment=encounter.assessment,
            plan=encounter.plan,
        )
    ]

    rx_result = await db.execute(
        select(Prescription)
        .where(Prescription.encounter_id == encounter_id)
        .options(selectinload(Prescription.items))
    )
    for prescription in rx_result.scalars().all():
        for item in prescription.items:
            resources.append(
                build_medication_request(
                    patient_id=visit.patient_id,
                    encounter_id=encounter.id,
                    prescription_id=prescription.id,
                    medicine_name=item.medicine_name,
                    dosage=item.dosage,
                    frequency=item.frequency,
                    duration_days=item.duration_days,
                    route=item.route,
                    instructions=item.instructions,
                )
            )

    mongo = get_mongo()
    bundle_doc = {
        "encounter_id": str(encounter.id),
        "patient_id": str(visit.patient_id),
        "direction": "hip_push",
        "resources": resources,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_result = await mongo["fhir_bundles"].insert_one(bundle_doc)

    await audit_service.write_audit_log(
        db,
        facility_id=visit.facility_id,
        user_id=encounter.created_by,
        role=None,
        action="encounter.close",
        resource_type="encounter",
        resource_id=encounter.id,
        patient_id=visit.patient_id,
        visit_id=visit.id,
        new_value={
            "ended_at": encounter.ended_at.isoformat(),
            "fhir_bundle_id": str(insert_result.inserted_id),
            "resource_count": len(resources),
        },
    )

    out = ClosedEncounterOut.model_validate(encounter)
    out.fhir_bundle_id = str(insert_result.inserted_id)
    return out