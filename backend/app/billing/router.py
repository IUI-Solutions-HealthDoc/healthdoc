"""billing module router — endpoints land here; see this module's GitHub issues.

B7-W2-01 (#168) adds the invoice-builder endpoints below the existing
stub. Prefix stays "/billing" only — /api/v1 is added wherever this
router gets included in main.py, same as the ping stub already assumed.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.billing import service
from app.billing.schemas import (
    InvoiceBuildRequest,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PMJAYEligibilityResponse,
)
from app.common.db import get_db
from app.common.security import get_current_user, require_roles

router = APIRouter(prefix="/billing", tags=["billing"])

_BILLING_ROLES = ("receptionist", "supervisor", "admin")


@router.get("/ping")
async def ping() -> dict:
    return {"module": "billing", "status": "stub"}


@router.get(
    "/visits/{visit_id}/invoice/preview",
    response_model=InvoicePreviewResponse,
    summary="Preview unbilled charges for a visit (read-only, no writes)",
)
def preview_visit_invoice(
    visit_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_roles(*_BILLING_ROLES)),
) -> InvoicePreviewResponse:
    return service.preview_invoice(db, visit_id)


@router.post(
    "/visits/{visit_id}/invoice/build",
    response_model=InvoiceBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregate unbilled visit charges onto the draft invoice",
)
def build_visit_invoice(
    visit_id: uuid.UUID,
    body: InvoiceBuildRequest = InvoiceBuildRequest(),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*_BILLING_ROLES)),
) -> InvoiceBuildResponse:
    return service.build_invoice(
        db, visit_id=visit_id, actor_user_id=user.id, dry_run=body.dry_run
    )


@router.get(
    "/visits/{visit_id}/pmjay-eligibility",
    response_model=PMJAYEligibilityResponse,
    summary="PM-JAY eligibility check (STUB — see service.check_pmjay_eligibility)",
)
def get_pmjay_eligibility(
    visit_id: uuid.UUID,
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_roles(*_BILLING_ROLES)),
) -> PMJAYEligibilityResponse:
    return service.check_pmjay_eligibility(db, patient_id=patient_id, visit_id=visit_id)
