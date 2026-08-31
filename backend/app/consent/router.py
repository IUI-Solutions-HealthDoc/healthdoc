"""consent module router — endpoints land here; see this module's GitHub issues.

data_access_log logging dependency lives in app/consent/access_log.py.

B7-W4-02 (Consent CRUD): get_current_actor_dependency populates the
per-request audit actor context so service.py's audited_mutation()
calls auto-fill user_id/role/ip_address/device_id. facility_id comes
from CurrentDbUser, never a request param (consent_records has no
facility_id column — see models.py).

Known cost, not fixed here: mutating routes resolve keycloak_sub ->
users.id more than once per request (CurrentDbUser +
get_current_actor_dependency each do their own lookup).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.deps import get_current_actor_dependency
from app.auth.deps import CurrentDbUser, CurrentUser, require_roles
from app.common.db import get_db
from app.common.enums import AccessChannel
from app.common.idempotency import check_idempotency, hash_request_body, record_idempotent_response
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

router = APIRouter(prefix="/consent", tags=["consent"])
DbSession = Annotated[AsyncSession, Depends(get_db)]

# A role that records, transitions or withdraws a consent must also be able to
# read the patient's current consent ledger first. The UI has always offered
# this workflow to receptionists and nurses, while these GET routes denied the
# read with 403 after patient selection.
_CONSENT_VIEW_ROLES = ("auditor", "admin", "doctor", "receptionist", "nurse")
_CONSENT_MUTATE_ROLES = ("receptionist", "nurse", "doctor", "admin")


# Module-liveness stub. Gated on `admin` for the same reason ot/, outbox/,
# blood_bank/, registration/ and security_audit/ already are: an
# unauthenticated endpoint on a health system is a finding regardless of
# payload, and the response still discloses which modules exist — useful
# reconnaissance, useless to a legitimate caller.
#
# Fourteen of these were still public after the WASA M4 pass closed five of
# them, so `make contract`-style module enumeration remained available to
# anyone who could reach the host. Nothing consumes them: no frontend call, no
# e2e script, no compose healthcheck (those probe Mongo and Redis directly),
# no Grafana panel.
@router.get("/ping", dependencies=[Depends(require_roles("admin"))])
async def ping() -> dict:
    return {"module": "consent", "status": "stub"}


@router.get(
    "/purposes",
    response_model=list[ConsentPurposeOut],
    summary="List active consent purposes (dropdown source for recording consent)",
)
async def list_consent_purposes(
    user: CurrentUser,  # open to any authenticated user — same as /departments
    db: DbSession,
) -> list[ConsentPurposeOut]:
    purposes = await service.list_consent_purposes(db)
    return [ConsentPurposeOut.model_validate(p) for p in purposes]


@router.get(
    "/patients/{patient_id}/records",
    response_model=list[ConsentRecordOut],
    # log_patient_data_access must be first: dependencies=[] resolves
    # before any handler-parameter Depends() (e.g. CurrentDbUser below).
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="consent_records",
                purpose_code="consent_review",
                access_channel=AccessChannel.API.value,
                consent_required=False,  # viewing someone's OWN consent log isn't itself consent-gated
            )
        ),
        Depends(require_roles(*_CONSENT_VIEW_ROLES)),
    ],
    summary="List a patient's consent records (logs to data_access_log)",
)
async def list_patient_consent_records(
    patient_id: uuid.UUID,
    user: CurrentDbUser,
    db: DbSession,
) -> list[ConsentRecordOut]:
    records = await service.list_consent_records_for_patient(
        db, patient_id, facility_id=user.facility_id
    )
    return [ConsentRecordOut.model_validate(r) for r in records]


@router.get(
    "/patients/{patient_id}/records/{consent_id}",
    response_model=ConsentRecordOut,
    # log_patient_data_access MUST be first: dependencies=[] resolves
    # before any handler-parameter Depends() (e.g. CurrentDbUser below),
    # and within this list, in the order listed.
    dependencies=[
        Depends(
            log_patient_data_access(
                resource_type="consent_records",
                purpose_code="consent_review",
                access_channel=AccessChannel.API.value,
                consent_required=False,
            )
        ),
        Depends(require_roles(*_CONSENT_VIEW_ROLES)),
    ],
)
async def get_consent_record(
    patient_id: uuid.UUID,
    consent_id: uuid.UUID,
    user: CurrentDbUser,
    db: DbSession,
) -> ConsentRecordOut:
    record = await service.get_consent_record(db, consent_id, facility_id=user.facility_id)
    if record.patient_id != patient_id:
        raise HTTPException(404, "Consent record not found")
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
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConsentRecordOut:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    endpoint = f"POST /consent/patients/{patient_id}/records"
    existing = await check_idempotency(
        db,
        idempotency_key,
        endpoint,
        hash_request_body(payload),
        user.id,
    )
    if existing is not None:
        return ConsentRecordOut.model_validate(existing.response_body)

    record = await service.create_consent_record(
        db,
        patient_id=patient_id,
        facility_id=user.facility_id,
        created_by=user.id,
        **payload.model_dump(),
    )
    response = ConsentRecordOut.model_validate(record)
    await record_idempotent_response(
        db,
        idempotency_key,
        endpoint,
        201,
        response.model_dump(mode="json"),
        user_id=user.id,
    )
    return response


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
    db: DbSession,
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
    db: DbSession,
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
