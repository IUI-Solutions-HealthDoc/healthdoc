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
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthUser, require_roles
from app.consent import service
from app.consent.access_log import log_patient_data_access
from app.consent.schemas import ConsentRecordOut
from app.common.db import get_db
from app.common.enums import AccessChannel

router = APIRouter(prefix="/consent", tags=["consent"])

# No dedicated role list confirmed for "who can view a patient's
# consent history" — auditor/DPO/admin is my best guess (schema doc §7
# names auditor/DPO as the readers of data_access_log itself; extending
# that to consent_records viewing). Confirm before merge.
_CONSENT_VIEW_ROLES = ("auditor", "admin", "doctor")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "consent", "status": "stub"}


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
