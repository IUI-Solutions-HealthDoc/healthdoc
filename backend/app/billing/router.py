"""billing module router — endpoints land here; see this module's GitHub issues.

B7-W2-01 (#168) adds the invoice-builder endpoints below the existing
ping stub. B7-W3-01 (#188) adds the payment/refund endpoints. Prefix
stays "/billing" only — /api/v1 is added wherever this router gets
included in main.py (matches app/common/config.py's api_prefix and the
existing ping stub's own prefix convention).

AUTH — app/auth/deps.py is now available (was not, in B7-W2-01). It
confirms the shape assumed back then: CurrentUser = Annotated[AuthUser,
Depends(get_current_user)], AuthUser has sub/username/roles (no .id —
see service.resolve_actor_user_id's updated docstring), and
require_roles(*allowed) is a factory returning a dependency that itself
depends on CurrentUser and returns AuthUser. The
`user: CurrentUser = Depends(require_roles(...))` pattern below still
type-checks fine (the explicit Depends(...) default overrides the
Annotated one) — no change needed from the B7-W2-01 version.

MODULE GATING — billing is listed in app/common/modules.py's
CORE_MODULES and in the schema doc as a module that "can NEVER be
disabled." Correctly NOT wrapped with require_module() for the
invoice/payment endpoints below. billing_refunds is a SEPARATE,
toggleable ModuleCode (schema doc §3 0027 / enums.ModuleCode) — "some
facilities route refunds through treasury manually" — so the refund
endpoint below IS wrapped with require_module("billing_refunds"),
unlike everything else in this router.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_roles
from app.billing import service
from app.billing.schemas import (
    DailyRevenueResponse,
    InvoiceBuildRequest,
    InvoiceBuildResponse,
    InvoicePreviewResponse,
    PaymentCreate,
    PaymentOut,
    PendingInvoicesResponse,
    PMJAYEligibilityResponse,
    RefundCreate,
    RefundOut,
    SchemeBreakdownResponse,
)
from app.common.db import get_db
from app.common.modules import require_module

router = APIRouter(prefix="/billing", tags=["billing"])

# No dedicated "billing" Keycloak realm role exists in the schema doc's
# role list (receptionist, doctor, nurse, lab_tech, radiology_tech,
# pharmacist, emergency, supervisor, admin, auditor, patient) — I've
# now confirmed this against docs/database-schema.md §8 directly (was
# only inferred in B7-W2-01). receptionist/supervisor/admin is still my
# best-effort mapping for who staffs a billing counter and posts
# invoice/payment activity — confirm with whoever owns role
# definitions.
_BILLING_ROLES = ("receptionist", "supervisor", "admin")

# Refund APPROVAL is a step up from posting a payment — a receptionist
# can collect cash, but approving a reversal against money already
# collected is the kind of action the schema doc's refunds.approved_by
# column implies needs a supervisor/admin sign-off, not front-desk
# self-service. This is my assumption, not something spelled out
# verbatim in the docs I have — flag for review; if refunds should stay
# receptionist-accessible, just use _BILLING_ROLES here instead.
_REFUND_APPROVAL_ROLES = ("supervisor", "admin")

# MIS is a financial-overview surface, not day-to-day counter work — no
# receptionist. auditor included since these are exactly the kind of
# aggregate financial figures an auditor role should be able to pull.
_MIS_ROLES = ("supervisor", "admin", "auditor")


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


# ---------------------------------------------------------------------
# Payments / refunds — B7-W3-01 (#188).
#
# Path shape here follows the schema doc's §4.4 API field contract
# table literally — /billing/invoices/{id}/payments and
# /billing/payments/{id}/refunds, keyed by invoice_id / payment_id —
# rather than the visit_id-based pattern the two /visits/{visit_id}/...
# endpoints above use. Those two predate this ticket (B7-W2-01) and
# were a deliberate per-visit framing for the invoice *builder*; a
# payment or refund isn't naturally scoped to a visit the same way (one
# invoice, many payments; one payment, many partial refunds), and the
# doc's own contract table addresses them by invoice_id/payment_id, so
# I've matched that rather than forcing them under /visits/{visit_id}/.
# Worth a second pair of eyes since it's a path-shape inconsistency
# within this same router — flag in review if the team wants everything
# unified under /visits/{visit_id}/....
# ---------------------------------------------------------------------


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment against an invoice (receipt is immutable once saved)",
)
async def record_invoice_payment(
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_BILLING_ROLES)),
) -> PaymentOut:
    actor_user_id = await service.resolve_actor_user_id(
        db,
        keycloak_sub=getattr(user, "sub", None),
        fallback_id=getattr(user, "id", None),
    )
    return await service.record_payment(db, invoice_id=invoice_id, body=body, actor_user_id=actor_user_id)


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a refund against a payment (reversal ledger entry — never edits the payment)",
    dependencies=[Depends(require_module("billing_refunds"))],
)
async def record_payment_refund(
    payment_id: uuid.UUID,
    body: RefundCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_REFUND_APPROVAL_ROLES)),
) -> RefundOut:
    actor_user_id = await service.resolve_actor_user_id(
        db,
        keycloak_sub=getattr(user, "sub", None),
        fallback_id=getattr(user, "id", None),
    )
    return await service.create_refund(db, payment_id=payment_id, body=body, actor_user_id=actor_user_id)


# ---------------------------------------------------------------------
# Billing MIS — B7-W3-02 (#189). Read-only. Always scoped to the
# caller's own facility (resolved server-side from the JWT, never a
# query param) — a facility's supervisor/auditor shouldn't be able to
# pull another facility's revenue by just changing a UUID in the URL.
# ---------------------------------------------------------------------


@router.get(
    "/mis/daily-revenue",
    response_model=DailyRevenueResponse,
    summary="Net revenue (payments minus refunds) per day for the caller's facility",
)
async def get_daily_revenue(
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_MIS_ROLES)),
) -> DailyRevenueResponse:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    return await service.get_daily_revenue(db, facility_id=facility_id, date_from=date_from, date_to=date_to)


@router.get(
    "/mis/pending-invoices",
    response_model=PendingInvoicesResponse,
    summary="Invoices with an outstanding balance for the caller's facility",
)
async def get_pending_invoices(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_MIS_ROLES)),
) -> PendingInvoicesResponse:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    return await service.get_pending_invoices(db, facility_id=facility_id)


@router.get(
    "/mis/scheme-breakdown",
    response_model=SchemeBreakdownResponse,
    summary="Billed/collected amounts grouped by scheme_code for invoices created in the given period",
)
async def get_scheme_breakdown(
    date_from: date = Query(default_factory=date.today),
    date_to: date = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(*_MIS_ROLES)),
) -> SchemeBreakdownResponse:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    return await service.get_scheme_breakdown(db, facility_id=facility_id, date_from=date_from, date_to=date_to)
