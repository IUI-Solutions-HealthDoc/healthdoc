"""billing module router — endpoints land here; see this module's GitHub issues.

B7-W2-01 (#168) adds the invoice-builder endpoints below the existing
ping stub. Prefix stays "/billing" only — /api/v1 is added wherever
this router gets included in main.py (matches app/common/config.py's
api_prefix and the existing ping stub's own prefix convention).

AUTH — app/auth/deps.py was not available to check directly. Import
path and CurrentUser/require_roles usage are inferred from
app/common/modules.py, which imports `from app.auth.deps import
CurrentUser` and describes require_module as working "like
require_roles" (implying require_roles already exists there). If the
real signature differs, only the Depends(...) wiring below needs to
change — service.py never touches CurrentUser directly.

MODULE GATING — billing is listed in app/common/modules.py's
CORE_MODULES and in the schema doc as a module that "can NEVER be
disabled." Correctly NOT wrapped with require_module() anywhere below.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_roles
from app.billing import service
from app.billing.schemas import (
    InvoiceBuildRequest,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PMJAYEligibilityResponse,
)
from app.common.db import get_db

router = APIRouter(prefix="/billing", tags=["billing"])

# No dedicated "billing" Keycloak realm role exists in the schema doc's
# role list (receptionist, doctor, nurse, lab_tech, radiology_tech,
# pharmacist, emergency, supervisor, admin, auditor, patient).
# receptionist/supervisor/admin is my best guess for who staffs a
# billing counter — confirm with whoever owns role definitions.
_BILLING_ROLES = ("receptionist", "supervisor", "admin")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "billing", "status": "stub"}


@router.get(
    "/visits/{visit_id}/invoice/preview",
    response_model=InvoicePreviewResponse,
    summary="Preview unbilled charges for a visit (read-only, no writes)",
)
async def preview_visit_invoice(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_roles(*_BILLING_ROLES)),
) -> InvoicePreviewResponse:
    return await service.preview_invoice(db, visit_id)


@router.post(
    "/visits/{visit_id}/invoice/build",
    response_model=InvoiceBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregate unbilled visit charges onto the draft invoice",
)
async def build_visit_invoice(
    visit_id: uuid.UUID,
    body: InvoiceBuildRequest = InvoiceBuildRequest(),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_BILLING_ROLES)),
) -> InvoiceBuildResponse:
    # CurrentUser's exact shape isn't confirmed (see module docstring).
    # If it already exposes the resolved app users.id, pass that as
    # fallback_id and no extra query runs; if it only carries the
    # Keycloak `sub` (as app/common/modules.py's usage suggests),
    # resolve_actor_user_id looks it up. Blame.created_by/updated_by and
    # audit_logs.user_id need users.id, never the Keycloak sub.
    actor_user_id = await service.resolve_actor_user_id(
        db,
        keycloak_sub=getattr(user, "sub", None),
        fallback_id=getattr(user, "id", None),
    )
    return await service.build_invoice(
        db, visit_id=visit_id, actor_user_id=actor_user_id, dry_run=body.dry_run
    )


@router.get(
    "/visits/{visit_id}/pmjay-eligibility",
    response_model=PMJAYEligibilityResponse,
    summary="PM-JAY eligibility check (STUB — see service.check_pmjay_eligibility)",
)
async def get_pmjay_eligibility(
    visit_id: uuid.UUID,
    patient_id: uuid.UUID,
    _user: CurrentUser = Depends(require_roles(*_BILLING_ROLES)),
) -> PMJAYEligibilityResponse:
    return service.check_pmjay_eligibility(patient_id=patient_id, visit_id=visit_id)
