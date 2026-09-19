"""Terminology search and specialty encounter endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.opd.models import Encounter, Visit
from app.terminology import service
from app.terminology.schemas import (
    SpecialtyEncounterCreate,
    SpecialtyEncounterOut,
    SpecialtyTemplateOut,
    TerminologySearchItem,
)

terminology_router = APIRouter(
    prefix="/terminology",
    tags=["terminology"],
)

clinical_router = APIRouter(
    prefix="/clinical",
    tags=["clinical-specialty"],
)

router = APIRouter()
router.include_router(terminology_router)
router.include_router(clinical_router)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@terminology_router.get("/search", response_model=list[TerminologySearchItem])
async def search_clinical_terms(
    q: Annotated[str, Query(min_length=1, description="Search query term or code")],
    system: Annotated[str, Query(description="Coding system: all, icd10, icd11, snomed")] = "all",
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 20,
) -> list[TerminologySearchItem]:
    """Search diagnoses across ICD-10, ICD-11, and SNOMED CT with instant in-memory response."""
    return service.search_terminology(q=q, system=system, limit=limit)


@clinical_router.get(
    "/specialty-templates",
    response_model=list[SpecialtyTemplateOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def list_specialty_templates() -> list[SpecialtyTemplateOut]:
    """List standard specialty examination templates (pediatric, cardiology, obstetrics)."""
    return service.get_specialty_templates()


@clinical_router.get(
    "/specialty-templates/{specialty_type}",
    response_model=SpecialtyTemplateOut,
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def get_specialty_template(specialty_type: str) -> SpecialtyTemplateOut:
    """Retrieve template definition for a specific clinical specialty."""
    tpl = service.get_specialty_template(specialty_type)
    if tpl is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "template_not_found", "message": f"Specialty template '{specialty_type}' not found"},
        )
    return tpl


@clinical_router.post(
    "/encounters/{encounter_id}/specialty",
    response_model=SpecialtyEncounterOut,
    status_code=201,
)
async def record_encounter_specialty_assessment(
    encounter_id: uuid.UUID,
    payload: SpecialtyEncounterCreate,
    current_user: CurrentDbUser,
    db: DbSession,
) -> SpecialtyEncounterOut:
    """Record or update structured specialty clinical findings for an encounter."""
    # Scope encounter to clinician's facility
    stmt = (
        select(Encounter, Visit.patient_id, Visit.facility_id)
        .join(Visit, Visit.id == Encounter.visit_id)
        .where(Encounter.id == encounter_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "encounter_not_found", "message": "Encounter not found"})

    encounter, patient_id, facility_id = row
    if current_user.facility_id != facility_id:
        raise HTTPException(status_code=403, detail={"code": "facility_mismatch", "message": "Access outside user facility"})

    tpl = service.get_specialty_template(payload.specialty_type)
    if tpl is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_specialty", "message": f"Unknown specialty type '{payload.specialty_type}'"},
        )

    record = await service.record_specialty_encounter(
        db,
        encounter_id=encounter_id,
        patient_id=patient_id,
        specialty_type=payload.specialty_type,
        clinical_data=payload.clinical_data,
        created_by=current_user.id,
    )
    return SpecialtyEncounterOut.model_validate(record)


@clinical_router.get(
    "/encounters/{encounter_id}/specialty",
    response_model=list[SpecialtyEncounterOut],
)
async def get_encounter_specialty_assessments(
    encounter_id: uuid.UUID,
    current_user: CurrentDbUser,
    db: DbSession,
) -> list[SpecialtyEncounterOut]:
    """Retrieve recorded specialty clinical findings for an encounter."""
    stmt = (
        select(Encounter, Visit.facility_id)
        .join(Visit, Visit.id == Encounter.visit_id)
        .where(Encounter.id == encounter_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "encounter_not_found", "message": "Encounter not found"})

    encounter, facility_id = row
    if current_user.facility_id != facility_id:
        raise HTTPException(status_code=403, detail={"code": "facility_mismatch", "message": "Access outside user facility"})

    records = await service.get_specialty_encounters(db, encounter_id=encounter_id)
    return [SpecialtyEncounterOut.model_validate(r) for r in records]
