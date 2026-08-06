"""billing module router — endpoints land here; see this module's GitHub issues.

B7-W2-01 (#168) invoice builder. B7-W3-01 (#188) payments/refunds.
B7-W3-02 (#189) MIS. Updated for schema doc v3.13.

MODULE GATING — v3.13 changed the "Only these five modules are optional"
list (§3 0027): pharmacy|lab|radiology|ot|blood_bank, and explicitly
lists "refunds" under Core — always on. There is no "billing_refunds"
ModuleCode anymore (confirmed against app/common/enums.ModuleCode — it
only defines the five toggleable modules). The refund endpoint below
carries no require_module() gate.

IDEMPOTENCY — v3.13 §4A.1 requires an Idempotency-Key header on every
POST that creates something, explicitly naming "payments, refunds".
Both POST endpoints below enforce it (400 if missing, 409 on key reuse
with a different body) via service.check_idempotency/store_idempotency
against the shared idempotency_keys table (0002, owned by B1 — read/
write only, no schema change made here).

PR REVIEW FIX (blocker 1 — app did not start):
CurrentUser (app/auth/deps.py) is already
Annotated[AuthUser, Depends(get_current_user)]. Every endpoint here used
to write `_user: CurrentUser = Depends(require_roles(...))`, which
supplies a dependency on BOTH the Annotated default AND the explicit
Depends() default — FastAPI refuses at import time
("Cannot specify `Depends` in `Annotated` and default value together").
That aborted app.main's import, which also aborted pytest collection for
the WHOLE repo, not just billing. Fixed by typing the parameter as the
plain `AuthUser` class (not the CurrentUser alias) wherever an explicit
Depends(require_roles(...)) is given — see app/audit/deps.py for another
module already using this exact pattern correctly.

AUDIT (app/audit, issue #290 — B7 rollout item):
The three mutating endpoints below (build, payment, refund) now also
depend on app.audit.deps.get_current_actor_dependency, alongside
require_roles(). That populates the per-request AuditActor context
(app/audit/context.py) so service.py's manual write_audit_log() calls
for invoice_items/payments/refunds (see service.py — those tables lack
a facility_id column and can't use the automatic listeners.py hook) get
a real user_id/role/ip_address/device_id instead of falling back to
None. Read-only endpoints (preview, MIS, pmjay-eligibility) don't need
this — nothing is written there for anyone to attribute.

BRANCH NOTE: this only imports cleanly once app/audit is actually
present on your checkout. It lives on `staging` (PR #261, merged
there) — if this branch was cut before that merge, or has since fallen
behind, `import app.billing.router` will raise
`ModuleNotFoundError: No module named 'app.audit...'`. Fix is
`git merge origin/staging` into this branch, NOT stripping the audit
wiring back out — the module genuinely exists, it just needs to be
pulled in locally.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.auth.deps import AuthUser, require_roles
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

router = APIRouter(prefix="/billing", tags=["billing"])

# No dedicated "billing" Keycloak realm role — confirmed against schema
# doc §7 role list. receptionist/supervisor/admin is our best mapping
# for who staffs a billing counter — confirm with role definitions owner.
_BILLING_ROLES = ("receptionist", "supervisor", "admin")

# Refund approval is a step up from posting a payment (refunds.approved_by
# implies sign-off) — not receptionist self-service. Flag if wrong.
_REFUND_APPROVAL_ROLES = ("supervisor", "admin")

# MIS: financial overview, not counter work. admin owns "billing config,
# facility MIS" per §Account governance; auditor for compliance reads.
_MIS_ROLES = ("supervisor", "admin", "auditor")


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key header is required.")
    return idempotency_key


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
    _user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
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
    user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> InvoiceBuildResponse:
    # §4A.1 lists "orders" but not invoices/invoice_items explicitly —
    # not adding Idempotency-Key enforcement here until that's confirmed
    # with whoever owns the reliability contract. Flag for review.
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
    _user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
) -> PMJAYEligibilityResponse:
    return service.check_pmjay_eligibility(patient_id=patient_id, visit_id=visit_id)


# ---------------------------------------------------------------------
# Payments / refunds — B7-W3-01 (#188). Keyed by invoice_id/payment_id
# per schema doc §4.4's contract table, not visit_id like the two
# endpoints above (those predate this ticket — see PR notes).
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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> PaymentOut:
    key = _require_idempotency_key(idempotency_key)
    endpoint = "POST /billing/invoices/{invoice_id}/payments"
    request_body = {"invoice_id": str(invoice_id), **body.model_dump(mode="json")}

    actor_user_id = await service.resolve_actor_user_id(
        db,
        keycloak_sub=getattr(user, "sub", None),
        fallback_id=getattr(user, "id", None),
    )
    cached = await service.check_idempotency(db, key, endpoint, request_body, actor_user_id)
    if cached is not None:
        return PaymentOut.model_validate(cached)

    result = await service.record_payment(db, invoice_id=invoice_id, body=body, actor_user_id=actor_user_id)
    await service.store_idempotency(db, key, endpoint, request_body, actor_user_id, result.model_dump(mode="json"))
    return result


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a refund against a payment (reversal ledger entry — never edits the payment)",
)
async def record_payment_refund(
    payment_id: uuid.UUID,
    body: RefundCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_REFUND_APPROVAL_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> RefundOut:
    key = _require_idempotency_key(idempotency_key)
    endpoint = "POST /billing/payments/{payment_id}/refunds"
    request_body = {"payment_id": str(payment_id), **body.model_dump(mode="json")}

    actor_user_id = await service.resolve_actor_user_id(
        db,
        keycloak_sub=getattr(user, "sub", None),
        fallback_id=getattr(user, "id", None),
    )
    cached = await service.check_idempotency(db, key, endpoint, request_body, actor_user_id)
    if cached is not None:
        return RefundOut.model_validate(cached)

    result = await service.create_refund(db, payment_id=payment_id, body=body, actor_user_id=actor_user_id)
    await service.store_idempotency(db, key, endpoint, request_body, actor_user_id, result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------
# Billing MIS — B7-W3-02 (#189). Scoped server-side to the caller's own
# facility. date_from/date_to default to the facility's OWN business
# date when omitted (resolved in service via facilities.timezone) —
# never date.today() here, which would be the server's/UTC date, not
# necessarily the facility's.
# ---------------------------------------------------------------------


@router.get(
    "/mis/daily-revenue",
    response_model=DailyRevenueResponse,
    summary="Net revenue (payments minus refunds) per day for the caller's facility",
)
async def get_daily_revenue(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_MIS_ROLES)),
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
    user: AuthUser = Depends(require_roles(*_MIS_ROLES)),
) -> PendingInvoicesResponse:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    return await service.get_pending_invoices(db, facility_id=facility_id)


@router.get(
    "/mis/scheme-breakdown",
    response_model=SchemeBreakdownResponse,
    summary="Billed/collected amounts grouped by scheme_code for invoices created in the given period",
)
async def get_scheme_breakdown(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_MIS_ROLES)),
) -> SchemeBreakdownResponse:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    return await service.get_scheme_breakdown(db, facility_id=facility_id, date_from=date_from, date_to=date_to)
