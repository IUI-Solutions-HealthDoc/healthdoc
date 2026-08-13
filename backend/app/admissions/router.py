"""admissions module router — #216 (B3-W5-01): IPD admission and
transfers, discharge summary API + FHIR stub. Stacked on
b3-w5-01-pr2-admit-transfer, which covers admit/transfer only.

Mounted into the app under the "ipd" module name (see app/ipd/router.py) —
app.main's MODULES list gates on "ipd", not "admissions", so this router
is re-exported there rather than imported directly.

Role mapping (_IPD_ROLES) is a best guess -- doctor/nurse/admin -- same
"flag if wrong" caveat billing's router leaves for its own role mapping;
schema.md §7 doesn't name an explicit IPD role set.

Idempotency-Key: schema.md §4A.1 names patients/visits/orders/payments/
refunds/dispenses/tokens/procedures explicitly, not admissions -- not
enforcing it here, same "not confirmed, flag for review" stance billing's
own build-invoice endpoint takes for an unlisted resource.

NOTE: the original draft of this endpoint validated the transfer
response against a bespoke TransferOut schema requiring an
`admission_id` field that transfer_patient()'s return value (an
Admission) doesn't have -- Admission's own PK is `id`, not
`admission_id`; that field only makes sense on child rows like
Discharge. Fixed by reusing AdmissionOut, which already matches the
shape transfer_patient() actually returns.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions import schemas, service
from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.auth.deps import AuthUser, require_roles
from app.common.db import get_db

router = APIRouter(prefix="/admissions", tags=["admissions"])

_IPD_ROLES = ("doctor", "nurse", "admin")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "admissions", "status": "ok"}


@router.post("", response_model=schemas.AdmissionOut, status_code=status.HTTP_201_CREATED)
async def create_admission(
    body: schemas.AdmissionCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_IPD_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> schemas.AdmissionOut:
    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=getattr(user, "sub", None), fallback_id=getattr(user, "id", None)
    )
    try:
        admission = await service.admit_patient(
            db,
            visit_id=body.visit_id,
            ward_id=body.ward_id,
            bed_id=body.bed_id,
            created_by=actor_id,
            reason=body.reason,
            admitted_at=body.admitted_at,
        )
    except service.VisitNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    except service.BedNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bed not found")
    except service.BedNotAvailable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bed is already occupied")
    return schemas.AdmissionOut.model_validate(admission)


@router.get("/{admission_id}", response_model=schemas.AdmissionOut)
async def get_admission(
    admission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*_IPD_ROLES)),
) -> schemas.AdmissionOut:
    admission = await service.get_admission(db, admission_id)
    if admission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission not found")
    return schemas.AdmissionOut.model_validate(admission)


@router.post("/{admission_id}/transfer", response_model=schemas.AdmissionOut)
async def transfer_admission(
    admission_id: uuid.UUID,
    body: schemas.TransferRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_IPD_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> schemas.AdmissionOut:
    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=getattr(user, "sub", None), fallback_id=getattr(user, "id", None)
    )
    admission = await service.get_admission(db, admission_id)
    if admission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission not found")
    try:
        admission = await service.transfer_patient(
            db, admission, to_ward_id=body.to_ward_id, to_bed_id=body.to_bed_id,
            moved_by=actor_id, reason=body.reason,
        )
    except service.BedNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target bed not found")
    except service.BedNotAvailable:
        raise HTTPException(status.HTTP_409_CONFLICT, "Target bed is already occupied")
    except service.AdmissionNotActive as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Admission is not active (status={e.current_status})")
    return schemas.AdmissionOut.model_validate(admission)


@router.post("/{admission_id}/discharge", response_model=schemas.DischargeOut)
async def discharge_admission(
    admission_id: uuid.UUID,
    body: schemas.DischargeRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_IPD_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> schemas.DischargeOut:
    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=getattr(user, "sub", None), fallback_id=getattr(user, "id", None)
    )
    admission = await service.get_admission(db, admission_id)
    if admission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission not found")
    try:
        discharge = await service.discharge_patient(
            db, admission,
            discharge_type=body.discharge_type,
            created_by=actor_id,
            discharge_summary=body.discharge_summary,
            follow_up_date=body.follow_up_date,
            destination_facility_id=body.destination_facility_id,
            destination_facility_name=body.destination_facility_name,
            discharged_at=body.discharged_at,
        )
    except service.AdmissionNotActive as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Admission is not active (status={e.current_status})")
    except service.TransferDestinationRequired:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                             "destination_facility_id or destination_facility_name is required "
                             "when discharge_type is 'transferred'")
    return schemas.DischargeOut.model_validate(discharge)


@router.get("/{admission_id}/discharge-summary", response_model=schemas.DischargeSummaryOut)
async def discharge_summary(
    admission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*_IPD_ROLES)),
) -> schemas.DischargeSummaryOut:
    admission = await service.get_admission(db, admission_id)
    if admission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission not found")
    discharge = await service.get_discharge(db, admission_id)
    movements = await service.get_movements(db, admission_id)
    return schemas.DischargeSummaryOut(
        admission=schemas.AdmissionOut.model_validate(admission),
        discharge=schemas.DischargeOut.model_validate(discharge) if discharge else None,
        movements=[schemas.MovementOut.model_validate(m) for m in movements],
    )
