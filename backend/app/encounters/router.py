"""backend/app/encounters/router.py -- /encounters endpoints.

created_by/updated_by come from current_db_user, never the request body (same
rule as opd/router.py). That sentence has been at the top of this file all
along and create_encounter did not follow it: it passed the payload straight to
the service, which wrote payload.created_by, payload.provider_user_id and a
facility copied from an unscoped visit lookup.

A note on how that survived review. `create_review` further down this same file
does it correctly — `reviewed_by=current_db_user.id, created_by=current_db_user.id`
— so the module contains a correct example of the rule sitting twenty lines
below a violation of it. Reading either one alone looks fine.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
from app.encounters import service
from app.encounters.schemas import (
    DiagnosisCreate, DiagnosisOut, DoctorReviewCreate, DoctorReviewOut,
    DoctorReviewStatusUpdate, EncounterCreate, EncounterOut, EncounterUpdate,
)

router = APIRouter(prefix="/encounters", tags=["encounters"])


async def _get_scoped_encounter(db: AsyncSession, encounter_id: UUID, caller_facility_id):
    """One encounter, or 404 — including when it exists at another facility.

    Every handler below routes through this. Before it, the whole module fetched
    by id with no facility comparison at all: any doctor, nurse or receptionist
    could read another hospital's consultation note, and PATCH could rewrite it.
    encounters.facility_id has existed since 0021; nothing was reading it.

    404 rather than 403 — 403 confirms the id exists, which is enough to
    enumerate another facility's encounters.
    """
    encounter = await service.get_encounter(db, encounter_id)
    if encounter is None or encounter.facility_id != caller_facility_id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    return encounter



@router.post("", response_model=EncounterOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def create_encounter(payload: EncounterCreate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db),
                            idempotency_key: Annotated[
                                str | None, Header(alias="Idempotency-Key")
                            ] = None) -> EncounterOut:
    """Open an encounter.

    This handler took `current_db_user` and never referenced it. Authorship,
    facility scope and the attending clinician all came from the request body,
    while line 1 of this file states the opposite rule. The docstring was the
    specification; the code was the bug.
    """
    endpoint = "POST /encounters"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return EncounterOut.model_validate(cached.response_body)

    try:
        encounter = await service.create_encounter(
            db, payload, actor_id=current_db_user.id, facility_id=current_db_user.facility_id,
        )
    except service.VisitNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="visit_not_found")
    except service.ProviderNotInFacility:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider_not_in_facility",
        )
    response = EncounterOut.model_validate(encounter)
    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            http_status.HTTP_201_CREATED,
            response.model_dump(mode="json"),
            current_db_user.id,
        )
    return response


@router.get("/{encounter_id}", response_model=EncounterOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def get_encounter(encounter_id: UUID, current_db_user: CurrentDbUser,
                         db: AsyncSession = Depends(get_db)) -> EncounterOut:
    encounter = await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    return EncounterOut.model_validate(encounter)


@router.get("/by-visit/{visit_id}", response_model=EncounterOut,
            dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def get_encounter_by_visit(
    visit_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> EncounterOut:
    """Resolve a real persisted encounter for standalone clinical screens."""
    encounter = await service.get_latest_encounter_for_visit(
        db, visit_id, current_db_user.facility_id,
    )
    if encounter is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="encounter_not_found",
        )
    return EncounterOut.model_validate(encounter)


@router.patch("/{encounter_id}", response_model=EncounterOut,
              dependencies=[Depends(require_roles("doctor", "admin"))])
async def update_encounter(encounter_id: UUID, payload: EncounterUpdate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db),
                            if_match: Annotated[
                                str | None, Header(alias="If-Match")
                            ] = None) -> EncounterOut:
    encounter = await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    if if_match is None:
        raise HTTPException(
            status_code=http_status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "if_match_required", "message": "If-Match header is required"},
        )
    try:
        expected_row_version = int(if_match)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_if_match", "message": "If-Match must be an integer row_version"},
        ) from exc
    try:
        encounter = await service.update_encounter(
            db,
            encounter,
            payload,
            actor_id=current_db_user.id,
            expected_row_version=expected_row_version,
        )
    except service.StaleEncounterWrite as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_write",
                "message": "Encounter was modified by another user",
                "current": EncounterOut.model_validate(exc.encounter).model_dump(mode="json"),
            },
        ) from exc
    return EncounterOut.model_validate(encounter)


@router.post("/{encounter_id}/diagnoses", response_model=DiagnosisOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "admin"))])
async def create_diagnosis(encounter_id: UUID, payload: DiagnosisCreate, current_db_user: CurrentDbUser,
                            db: AsyncSession = Depends(get_db),
                            idempotency_key: Annotated[
                                str | None, Header(alias="Idempotency-Key")
                            ] = None) -> DiagnosisOut:
    if payload.encounter_id != encounter_id:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="encounter_id_mismatch")
    await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    endpoint = f"POST /encounters/{encounter_id}/diagnoses"
    if idempotency_key:
        cached = await check_idempotency(
            db,
            idempotency_key,
            endpoint,
            hash_request_body(payload),
            current_db_user.id,
        )
        if cached is not None:
            return DiagnosisOut.model_validate(cached.response_body)
    diagnosis = await service.create_diagnosis(db, payload, actor_id=current_db_user.id)
    response = DiagnosisOut.model_validate(diagnosis)
    if idempotency_key:
        await record_idempotent_response(
            db,
            idempotency_key,
            endpoint,
            http_status.HTTP_201_CREATED,
            response.model_dump(mode="json"),
            current_db_user.id,
        )
    return response


@router.get("/{encounter_id}/diagnoses", response_model=list[DiagnosisOut],
            dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def list_diagnoses(encounter_id: UUID, current_db_user: CurrentDbUser,
                          db: AsyncSession = Depends(get_db)) -> list[DiagnosisOut]:
    await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    diagnoses = await service.list_diagnoses(db, encounter_id)
    return [DiagnosisOut.model_validate(d) for d in diagnoses]



@router.post("/{encounter_id}/reviews", response_model=DoctorReviewOut, status_code=http_status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles("doctor", "admin"))])
async def create_review(encounter_id: UUID, payload: DoctorReviewCreate, current_db_user: CurrentDbUser,
                         db: AsyncSession = Depends(get_db)) -> DoctorReviewOut:
    """#200: doctor 'receives' the result(s) for this encounter by opening a
    review row -- starts at status='pending'. Optionally scoped to one
    incoming lab/radiology item; leave both null for a general
    encounter sign-off."""
    await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    try:
        review = await service.create_review(
            db,
            encounter_id=encounter_id,
            reviewed_by=current_db_user.id,
            created_by=current_db_user.id,
            lab_order_item_id=payload.lab_order_item_id,
            radiology_order_item_id=payload.radiology_order_item_id,
            notes=payload.notes,
        )
    except service.EncounterNotFound:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    return DoctorReviewOut.model_validate(review)


@router.get("/{encounter_id}/reviews", response_model=list[DoctorReviewOut],
            dependencies=[Depends(require_roles("doctor", "nurse", "admin"))])
async def list_reviews(encounter_id: UUID, current_db_user: CurrentDbUser,
                        db: AsyncSession = Depends(get_db)) -> list[DoctorReviewOut]:
    await _get_scoped_encounter(db, encounter_id, current_db_user.facility_id)
    reviews = await service.list_reviews(db, encounter_id)
    return [DoctorReviewOut.model_validate(r) for r in reviews]


@router.patch("/reviews/{review_id}", response_model=DoctorReviewOut,
              dependencies=[Depends(require_roles("doctor", "admin"))])
async def update_review(review_id: UUID, payload: DoctorReviewStatusUpdate, current_db_user: CurrentDbUser,
                         db: AsyncSession = Depends(get_db)) -> DoctorReviewOut:
    """Sign-off transition: pending -> reviewed -> signed_off, one step at
    a time. 404 unknown review, 409 on an invalid/backward/skip transition
    (includes re-signing an already signed_off review)."""
    review = await service.get_review(db, review_id)
    if review is None or review.facility_id != current_db_user.facility_id:
        # Signing off another facility's clinical review is a clinical act
        # attributed to the wrong hospital. 404, not 403 — see
        # _get_scoped_encounter.
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="review_not_found")

    try:
        review = await service.update_review_status(
            db, review, new_status=payload.status, updated_by=current_db_user.id, notes=payload.notes,
        )
    except service.InvalidReviewTransition as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "code": "invalid_review_transition",
                "message": f"Cannot move review from '{exc.current_status}' to '{exc.requested_status}'",
            },
        )
    return DoctorReviewOut.model_validate(review)
