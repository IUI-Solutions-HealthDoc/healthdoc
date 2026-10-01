"""backend/app/allergies/router.py -- /allergies endpoints (#286, schema v3.14 §3 0032).

The server-side prescribing gate already existed in service.check_prescription_item and
runs on every prescription save. What was missing was any way to populate or read the
register over the API — until now the only way in was direct SQL, which meant the gate
had nothing to check against in practice.

There is deliberately **no DELETE**. Allergy records are corrected via status
(`refuted`, `entered_in_error`, `inactive`), never removed: a deleted allergy that was
real is precisely the failure mode 0032's status enum exists to prevent.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies import service
from app.allergies.schemas import AllergyCheckOut, AllergyCreate, AllergyOut, AllergyStatusUpdate
from app.allergies.service import AllergyVersionConflict
from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/allergies", tags=["allergies"])


async def _assert_patient_in_facility(db: AsyncSession, patient_id: UUID, facility_id: UUID) -> None:
    """The allergies table has no facility_id — scope comes through the patient.

    Without this, any clinician could read, add to or overturn another
    hospital's allergy register. An allergy marked `refuted` by someone who
    never saw the patient is the specific failure 0032's status enum exists to
    prevent, and the prescribing gate reads this register on every save.

    404, not 403 — 403 confirms the patient exists.
    """
    from app.patients.models import Patient

    patient = await db.get(Patient, patient_id)
    if patient is None or patient.facility_id != facility_id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "patient_not_found")


async def _scoped_allergy(db: AsyncSession, allergy_id: UUID, facility_id: UUID):
    """One allergy, or 404 — resolved through its patient's facility."""
    from app.allergies.models import Allergy
    from app.patients.models import Patient

    allergy = await db.get(Allergy, allergy_id)
    if allergy is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "allergy_not_found")
    patient = await db.get(Patient, allergy.patient_id)
    if patient is None or patient.facility_id != facility_id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "allergy_not_found")
    return allergy



@router.get(
    "/patients/{patient_id}/check",
    response_model=AllergyCheckOut,
    dependencies=[Depends(require_roles("doctor", "pharmacist", "admin"))],
    summary="Pre-flight allergy check for one prescribed item (does not write)",
)
async def check_patient_allergy(
    patient_id: UUID,
    current_db_user: CurrentDbUser,
    ingredient_code: str | None = Query(
        default=None,
        description="The item's ingredient code. Absent means the check CANNOT run — "
                    "that is reported as 'uncheckable', never as 'clear'.",
    ),
    medicine_name: str = Query(default="", description="For the message text only."),
    db: AsyncSession = Depends(get_db),
) -> AllergyCheckOut:
    """Answer the prescribing screen's "can I prescribe this?" before it submits.

    Enforcement already lives on POST /orders/prescriptions, which raises
    AllergyConflict -> 409. This endpoint does not replace that and deliberately
    writes nothing; it exists so the warning a clinician sees is produced by the
    same matcher that will decide the write.

    Before this, the browser reimplemented the match: it filtered the allergy
    list client-side and blocked on `severity === "anaphylaxis"` while the
    server blocks on `is_absolute`. Those two agree today — is_absolute is a
    derived property returning exactly that comparison — but they were two
    independent statements of one safety rule, and the one on screen is what a
    clinician acts on.

    The three outcomes mirror service.check_prescription_item, including the
    distinction its docstring insists on: an item with no ingredient_code is
    'unknown', not 'clear'. The service returns None for both because it cannot
    block on a guess, and says the caller must tell the clinician the check
    could not be performed. This endpoint is that caller.
    """
    await _assert_patient_in_facility(db, patient_id, current_db_user.facility_id)

    if not ingredient_code:
        return AllergyCheckOut(
            kind="uncheckable",
            medicine_name=medicine_name,
            allergy=None,
            message=(
                "No ingredient code on this item — the allergy check could not be "
                "performed. Confirm with the patient before prescribing."
            ),
        )

    try:
        # override_reason is deliberately not accepted here. This is a read: a
        # clinician's written justification belongs on the write that records
        # it, not on a screen refresh that could be repeated silently.
        await service.check_prescription_item(
            db,
            patient_id=patient_id,
            ingredient_code=ingredient_code,
            override_reason=None,
        )
    except service.AllergyConflict as conflict:
        allergy = conflict.allergy
        if conflict.absolute:
            return AllergyCheckOut(
                kind="block",
                medicine_name=medicine_name,
                allergy=AllergyOut.model_validate(allergy),
                message=(
                    f"Anaphylaxis to {allergy.substance_text}. "
                    "This cannot be prescribed or overridden."
                ),
            )
        return AllergyCheckOut(
            kind="override_required",
            medicine_name=medicine_name,
            allergy=AllergyOut.model_validate(allergy),
            message=(
                f"{allergy.substance_text} ({allergy.severity}): "
                f"{allergy.reaction or 'no reaction recorded'}. "
                "A written reason is required to proceed."
            ),
        )

    return AllergyCheckOut(
        kind="clear",
        medicine_name=medicine_name,
        allergy=None,
        message="No active coded allergy matches this item.",
    )


@router.get(
    "/patients/{patient_id}",
    response_model=list[AllergyOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "pharmacist", "admin"))],
)
async def list_patient_allergies(
    patient_id: UUID,
    current_db_user: CurrentDbUser,
    include_inactive: bool = Query(
        default=False,
        description="Include refuted / entered_in_error / inactive entries. The "
                    "prescribing banner wants active only; the review screen wants all.",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[AllergyOut]:
    await _assert_patient_in_facility(db, patient_id, current_db_user.facility_id)
    rows = await service.list_allergies(db, patient_id, include_inactive=include_inactive)
    return [AllergyOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=AllergyOut,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def create_allergy(
    payload: AllergyCreate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    await _assert_patient_in_facility(db, payload.patient_id, current_db_user.facility_id)
    allergy = await service.record_allergy(db, payload, recorded_by=current_db_user.id)
    return AllergyOut.model_validate(allergy)


@router.patch(
    "/{allergy_id}/status",
    response_model=AllergyOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def update_allergy_status(
    allergy_id: UUID,
    payload: AllergyStatusUpdate,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    await _scoped_allergy(db, allergy_id, current_db_user.facility_id)
    try:
        allergy = await service.set_status(
            db,
            allergy_id,
            status=payload.status,
            row_version=payload.row_version,
            updated_by=current_db_user.id,
        )
    except AllergyVersionConflict as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"code": "row_version_conflict", "message": str(exc)},
        ) from exc
    if allergy is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="allergy_not_found"
        )
    return AllergyOut.model_validate(allergy)


@router.post(
    "/{allergy_id}/verify",
    response_model=AllergyOut,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def verify_allergy(
    allergy_id: UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> AllergyOut:
    """Clinician confirmation of a reported allergy.

    Restricted to doctors: a nurse or receptionist can record what an attendant
    reports, but verification is a clinical judgement and is what downstream
    reviewers will read as such.
    """
    await _scoped_allergy(db, allergy_id, current_db_user.facility_id)
    allergy = await service.verify_allergy(db, allergy_id, verified_by=current_db_user.id)
    if allergy is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="allergy_not_found"
        )
    return AllergyOut.model_validate(allergy)
