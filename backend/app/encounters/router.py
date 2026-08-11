"""backend/app/encounters/router.py -- /encounters endpoints. created_by/updated_by come
from current_db_user, never the request body (same rule as opd/router.py)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.encounters import service
from app.encounters.schemas import (
    DiagnosisCreate, DiagnosisOut, EncounterCreate, EncounterOut, EncounterUpdate,
)

router = APIRouter(prefix="/encounters", tags=["encounters"])


@router.post("", response_model=EncounterOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_encounter(payload: EncounterCreate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db)) -> EncounterOut:
    encounter = await service.create_encounter(db, payload)
    return EncounterOut.model_validate(encounter)


@router.get("/{encounter_id}", response_model=EncounterOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def get_encounter(encounter_id: UUID, current_db_user: CurrentDbUser,
                         db: AsyncSession = Depends(get_db)) -> EncounterOut:
    encounter = await service.get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    return EncounterOut.model_validate(encounter)


@router.patch("/{encounter_id}", response_model=EncounterOut,
              dependencies=[Depends(require_roles("doctor", "admin"))])
async def update_encounter(encounter_id: UUID, payload: EncounterUpdate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db)) -> EncounterOut:
    encounter = await service.get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    encounter = await service.update_encounter(db, encounter, payload)
    return EncounterOut.model_validate(encounter)


@router.post("/{encounter_id}/diagnoses", response_model=DiagnosisOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "admin"))])
async def create_diagnosis(encounter_id: UUID, payload: DiagnosisCreate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db)) -> DiagnosisOut:
    if payload.encounter_id != encounter_id:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="encounter_id_mismatch")
    diagnosis = await service.create_diagnosis(db, payload)
    return DiagnosisOut.model_validate(diagnosis)


@router.get("/{encounter_id}/diagnoses", response_model=list[DiagnosisOut],
            dependencies=[Depends(require_roles("doctor", "nurse", "receptionist", "admin"))])
async def list_diagnoses(encounter_id: UUID, current_db_user: CurrentDbUser,
                          db: AsyncSession = Depends(get_db)) -> list[DiagnosisOut]:
    diagnoses = await service.list_diagnoses(db, encounter_id)
    return [DiagnosisOut.model_validate(d) for d in diagnoses]
