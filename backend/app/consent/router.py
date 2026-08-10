"""consent module router — endpoints land here; see this module's GitHub issues.

data_access_log logging dependency (ticket: decorator on patient-data
GETs, with purpose_code) lives in app/consent/access_log.py — see that
file's docstring for the design (dependency factory, own DB session so
denials still get logged despite request-transaction rollback).

The /patients/{patient_id}/records route below is a minimal real
endpoint that uses it, so the decorator is proven against something
that actually runs rather than shipped as unused utility code. Other
modules' own patient-data GET routes (patients, visits, orders, lab,
...) need their owners to import and apply log_patient_data_access on
their own routers — not done here, not this module's files to touch.

B7-W4-02 (Consent CRUD) endpoints below reuse
app.audit.deps.get_current_actor_dependency exactly as its own
docstring recommends ("add alongside require_roles() on any route that
mutates data") — it populates the per-request actor context so
service.py's audited_mutation() calls can auto-fill user_id/role/
ip_address/device_id without this file duplicating that resolution
logic. facility_id comes from CurrentDbUser, never a request param —
consent_records has no facility_id column of its own (see models.py),
so the audit row is scoped to the ACTING staff member's facility.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.deps import get_current_actor_dependency
from app.auth.deps import AuthUser, CurrentDbUser, CurrentUser, require_roles
from app.consent import service
from app.consent.access_log import log_patient_data_access
from app.consent.schemas import (
    ConsentPurposeOut,
    ConsentRecordCreate,
    ConsentRecordOut,
    ConsentStatusTransitionIn,
    ConsentWithdrawalCreate,
    ConsentWithdrawalOut,
)
from app.common.db import get_db
from app.common.enums import AccessChannel

router = APIRouter(prefix="/consent", tags=["consent"])

# No dedicated role list confirmed for "who can view a patient's
# consent history" — auditor/DPO/admin is my best guess (schema doc §7
# names auditor/DPO as the readers of data_access_log itself; extending
# that to consent_records viewing). Confirm before merge.
_CONSENT_VIEW_ROLES = ("auditor", "admin", "doctor")

# No dedicated role list confirmed for "who collects/updates a
# patient's consent" either — reception/nursing/doctor/admin is the
# best guess for staff present at the point consent is asked for.
# Confirm before merge, same as _CONSENT_VIEW_ROLES above.
_CONSENT_MUTATE_ROLES = ("receptionist", "nurse", "doctor", "admin")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "consent", "status": "stub"}


@router.get(
    "/purposes",
    response_model=list[ConsentPurposeOut],
    summary="List active consent purposes (dropdown source for recording consent)",
)
async def list_consent_purposes(
    user: CurrentUser,  # open to any authenticated user — same as /departments
    db: AsyncSession = Depends(get_db),
) -> list[ConsentPurposeOut]:
    purposes = await service.list_consent_purposes(db)
    return [ConsentPurposeOut.model_validate(p) for p in purposes]


@router.get(
    "/patients/{patient_id}/records",
    response_model=list[ConsentRecordOut],
    # log_patient_data_access listed FIRST so the access attempt is
    # recorded even if a later dependency in this list (none yet, but
    # e.g. a future patient-existence check) rejects the request.
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="consent_records",
                purpose_code="consent_review",
                access_channel=AccessChannel.API.value,
                consent_required=False,  # viewing someone's OWN consent log isn't itself consent-gated
            )
        )
    ],
    summary="List a patient's consent records (logs to data_access_log)",
)
async def list_patient_consent_records(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*_CONSENT_VIEW_ROLES)),
) -> list[ConsentRecordOut]:
    records = await service.list_consent_records_for_patient(db, patient_id)
    return [ConsentRecordOut.model_validate(r) for r in records]


@router.get(
    "/records/{consent_id}",
    response_model=ConsentRecordOut,
    dependencies=[Depends(require_roles(*_CONSENT_VIEW_ROLES))],
)
async def get_consent_record(
    consent_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ConsentRecordOut:
    record = await service.get_consent_record(db, consent_id)
    return ConsentRecordOut.model_validate(record)


@router.post(
    "/patients/{patient_id}/records",
    response_model=ConsentRecordOut,
    status_code=201,
    dependencies=[
        Depends(require_roles(*_CONSENT_MUTATE_ROLES)),
        Depends(get_current_actor_dependency),
    ],
)
async def create_consent_record(
    patient_id: uuid.UUID,
    payload: ConsentRecordCreate,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ConsentRecordOut:
    record = await service.create_consent_record(
        db,
        patient_id=patient_id,
        facility_id=user.facility_id,
        created_by=user.id,
        **payload.model_dump(),
    )
    return ConsentRecordOut.model_validate(record)


@router.patch(
    "/records/{consent_id}/status",
    response_model=ConsentRecordOut,
    dependencies=[
        Depends(require_roles(*_CONSENT_MUTATE_ROLES)),
        Depends(get_current_actor_dependency),
    ],
    summary="Approve or deny a 'requested' consent (the only direct status transition)",
)
async def transition_consent_status(
    consent_id: uuid.UUID,
    payload: ConsentStatusTransitionIn,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ConsentRecordOut:
    record = await service.transition_consent_status(
        db,
        consent_id,
        new_status=payload.status,
        reason=payload.reason,
        facility_id=user.facility_id,
        updated_by=user.id,
    )
    return ConsentRecordOut.model_validate(record)


@router.post(
    "/records/{consent_id}/withdraw",
    response_model=ConsentWithdrawalOut,
    status_code=201,
    dependencies=[
        Depends(require_roles(*_CONSENT_MUTATE_ROLES)),
        Depends(get_current_actor_dependency),
    ],
    summary="Withdraw a granted consent (flips status -> revoked via trg_consent_withdrawals_flip_status)",
)
async def withdraw_consent(
    consent_id: uuid.UUID,
    payload: ConsentWithdrawalCreate,
    user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> ConsentWithdrawalOut:
    withdrawal = await service.withdraw_consent(
        db,
        consent_id,
        withdrawn_by_type=payload.withdrawn_by_type,
        withdrawn_by_user_id=payload.withdrawn_by_user_id,
        reason=payload.reason,
        facility_id=user.facility_id,
    )
    return ConsentWithdrawalOut.model_validate(withdrawal)
