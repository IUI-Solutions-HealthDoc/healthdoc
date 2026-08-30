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
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditActor
from app.audit.deps import get_current_actor_dependency
from app.auth.deps import AuthUser, CurrentDbUser, require_roles
from app.billing import service
from app.billing.models import Invoice, InvoiceItem, Payment, Refund
from app.billing.schemas import (
    DailyRevenueResponse,
    InvoiceBuildRequest,
    InvoiceBuildResponse,
    InvoiceDetailOut,
    InvoiceLineOut,
    InvoiceListItemOut,
    InvoiceListOut,
    PaymentWithRefundsOut,
    RefundOnPaymentOut,
    InvoicePreviewResponse,
    PaymentCreate,
    PaymentOut,
    PendingInvoicesResponse,
    PMJAYEligibilityResponse,
    RefundCreate,
    RefundOut,
    SchemeBreakdownResponse,
    TariffCreate,
    TariffOut,
)
from app.common.db import get_db
from app.patients.models import Patient

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
    return {"module": "billing", "status": "stub"}


# ---------------------------------------------------------------------
# Facility scoping (P0.4)
#
# list_invoices scopes correctly because it was written after CurrentDbUser
# existed. The by-id endpoints below predate it and compared nothing: a clerk
# at facility A could preview and BUILD an invoice for another facility's
# visit, record a PAYMENT against another facility's invoice, and record a
# REFUND against another facility's payment. The last two move money.
#
# 404 rather than 403 — 403 confirms the id exists, which is enough to
# enumerate another facility's invoices and payments.
# ---------------------------------------------------------------------

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


async def _assert_visit_in_facility(db: AsyncSession, visit_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    from app.opd.models import Visit

    found = (
        await db.execute(
            select(Visit.id).where(Visit.id == visit_id, Visit.facility_id == facility_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise _NOT_FOUND


async def _assert_invoice_in_facility(db: AsyncSession, invoice_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    found = (
        await db.execute(
            select(Invoice.id).where(Invoice.id == invoice_id, Invoice.facility_id == facility_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise _NOT_FOUND


async def _assert_payment_in_facility(db: AsyncSession, payment_id: uuid.UUID, facility_id: uuid.UUID) -> None:
    """payments has no facility_id — it is reached through its invoice."""
    from app.billing.models import Payment

    found = (
        await db.execute(
            select(Payment.id)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(Payment.id == payment_id, Invoice.facility_id == facility_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise _NOT_FOUND


@router.get(
    "/invoices",
    response_model=InvoiceListOut,
    dependencies=[Depends(require_roles(*_BILLING_ROLES))],
)
async def list_invoices(
    current_db_user: CurrentDbUser,
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> InvoiceListOut:
    filters = [Invoice.facility_id == current_db_user.facility_id]
    if status_filter:
        filters.append(Invoice.status == status_filter)

    total = (
        await db.execute(select(func.count()).select_from(Invoice).where(*filters))
    ).scalar_one()
    result = await db.execute(
        select(Invoice, Patient.full_name, Patient.uhid, Patient.thid)
        .join(Patient, Patient.id == Invoice.patient_id)
        .where(*filters)
        .order_by(Invoice.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        InvoiceListItemOut(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            visit_id=invoice.visit_id,
            patient_id=invoice.patient_id,
            patient_full_name=patient_full_name,
            patient_identifier=uhid or thid or "—",
            status=invoice.status,
            gross_amount=invoice.gross_amount,
            net_amount=invoice.net_amount,
            scheme_code=invoice.scheme_code,
            row_version=invoice.row_version,
            created_at=invoice.created_at,
        )
        for invoice, patient_full_name, uhid, thid in result.all()
    ]
    return InvoiceListOut(items=items, page=page, page_size=page_size, total=total)


@router.get(
    "/visits/{visit_id}/invoice/preview",
    response_model=InvoicePreviewResponse,
    summary="Preview unbilled charges for a visit (read-only, no writes)",
)
async def preview_visit_invoice(
    visit_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
) -> InvoicePreviewResponse:
    await _assert_visit_in_facility(db, visit_id, current_db_user.facility_id)
    return await service.preview_invoice(db, visit_id)


@router.post(
    "/visits/{visit_id}/invoice/build",
    response_model=InvoiceBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregate unbilled visit charges onto the draft invoice",
)
async def build_visit_invoice(
    visit_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    body: InvoiceBuildRequest = InvoiceBuildRequest(),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> InvoiceBuildResponse:
    await _assert_visit_in_facility(db, visit_id, current_db_user.facility_id)
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


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailOut,
    dependencies=[Depends(require_roles(*_BILLING_ROLES))],
    summary="One invoice with its charge lines, receipts and remaining balance",
)
async def get_invoice(
    invoice_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> InvoiceDetailOut:
    """Replaces three frontend mocks that had no backend at all — getInvoice,
    listPayments and getInvoiceBalance.

    One endpoint rather than three because it is one screen, and because a
    balance assembled in the browser from separate calls can show a total that
    never existed at any single moment.

    Declared before /invoices/{invoice_id}/issue is irrelevant to matching —
    the paths differ — but note it must stay below the literal /invoices route.
    """
    await _assert_invoice_in_facility(db, invoice_id, current_db_user.facility_id)

    row = (
        await db.execute(
            select(Invoice, Patient.full_name, Patient.uhid, Patient.thid)
            .join(Patient, Patient.id == Invoice.patient_id)
            .where(Invoice.id == invoice_id)
        )
    ).one_or_none()
    if row is None:
        # _assert_invoice_in_facility already passed, so this is a patient row
        # that vanished — not a scoping failure.
        raise HTTPException(status_code=404, detail={"code": "invoice_not_found"})
    invoice, patient_full_name, uhid, thid = row

    lines = (
        (
            await db.execute(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice_id)
                .order_by(InvoiceItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    payments = (
        (
            await db.execute(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.collected_at)
            )
        )
        .scalars()
        .all()
    )

    # Refunds nested per receipt. They were write-only before this — created by
    # POST /billing/payments/{id}/refunds and readable nowhere — so a screen
    # could show a payment while silently omitting its reversal, and the
    # balance would disagree with the receipt in the patient's hand.
    refunds_by_payment: dict = {}
    if payments:
        refund_rows = (
            await db.execute(
                select(Refund)
                .where(Refund.payment_id.in_([p.id for p in payments]))
                .order_by(Refund.refunded_at)
            )
        ).scalars().all()
        for r in refund_rows:
            refunds_by_payment.setdefault(r.payment_id, []).append(
                RefundOnPaymentOut.model_validate(r)
            )

    # The same helper record_payment uses to decide partially_paid vs paid.
    # Deliberately not reimplemented here: two versions of this arithmetic
    # would eventually disagree, and the one on screen is the one a patient is
    # asked to settle.
    total_paid, total_refunded = await service._payment_totals_for_invoice(db, invoice_id)
    balance_due = Decimal(invoice.net_amount) - (total_paid - total_refunded)

    return InvoiceDetailOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        visit_id=invoice.visit_id,
        patient_id=invoice.patient_id,
        patient_full_name=patient_full_name,
        patient_identifier=uhid or thid or "—",
        facility_id=invoice.facility_id,
        status=invoice.status,
        gross_amount=invoice.gross_amount,
        discount_amount=invoice.discount_amount,
        scheme_adjustment=invoice.scheme_adjustment,
        net_amount=invoice.net_amount,
        scheme_code=invoice.scheme_code,
        row_version=invoice.row_version,
        created_at=invoice.created_at,
        lines=[InvoiceLineOut.model_validate(line) for line in lines],
        payments=[
            PaymentWithRefundsOut(
                id=p.id, receipt_number=p.receipt_number, invoice_id=p.invoice_id,
                amount=p.amount, currency=p.currency, mode=p.mode, status=p.status,
                collected_at=p.collected_at.isoformat(),
                refunds=refunds_by_payment.get(p.id, []),
            )
            for p in payments
        ],
        total_paid=total_paid,
        total_refunded=total_refunded,
        balance_due=balance_due,
    )


@router.post(
    "/invoices/{invoice_id}/issue",
    response_model=InvoiceListItemOut,
    status_code=status.HTTP_200_OK,
    summary="Issue a draft invoice, making it payable and freezing its amounts",
)
async def issue_invoice(
    invoice_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(None, alias="If-Match"),
    user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> InvoiceListItemOut:
    """The missing half of the billing journey.

    build -> **issue** -> pay. Without this step `record_payment` rejects every
    invoice the application builds, because build creates 'draft' and payment
    requires 'issued'. See service.issue_invoice for how that stayed hidden.

    If-Match carries the row_version read from the invoice. It is required, not
    optional: issuing freezes the amounts, and a stale client would freeze an
    invoice that is missing a charge line appended since it loaded.
    """
    await _assert_invoice_in_facility(db, invoice_id, current_db_user.facility_id)

    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "if_match_required",
                "message": "If-Match: <row_version> is required to issue an invoice",
            },
        )
    try:
        expected_row_version = int(if_match)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_if_match",
                "message": "If-Match must be an integer row_version",
            },
        )

    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=user.sub, fallback_id=current_db_user.id
    )
    invoice = await service.issue_invoice(
        db,
        invoice_id=invoice_id,
        updated_by=actor_id,
        expected_row_version=expected_row_version,
    )
    await db.commit()
    await db.refresh(invoice)

    patient = await db.get(Patient, invoice.patient_id)
    return InvoiceListItemOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        visit_id=invoice.visit_id,
        patient_id=invoice.patient_id,
        patient_full_name=patient.full_name if patient else "",
        # Same fallback chain as list_invoices above — a THID-only patient has
        # no UHID, and the two must not disagree between the list and this row.
        patient_identifier=(patient.uhid or patient.thid or "—") if patient else "—",
        status=invoice.status,
        gross_amount=invoice.gross_amount,
        net_amount=invoice.net_amount,
        scheme_code=invoice.scheme_code,
        row_version=invoice.row_version,
        created_at=invoice.created_at,
    )


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
    current_db_user: CurrentDbUser,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_BILLING_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> PaymentOut:
    await _assert_invoice_in_facility(db, invoice_id, current_db_user.facility_id)
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
    current_db_user: CurrentDbUser,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_REFUND_APPROVAL_ROLES)),
    _actor: AuditActor = Depends(get_current_actor_dependency),
) -> RefundOut:
    await _assert_payment_in_facility(db, payment_id, current_db_user.facility_id)
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


# ============================================================ charge_master admin (#287)
#
# 0033 created charge_master in July and nothing read or wrote it — pricing.py
# still carries hardcoded lab/radiology dicts with a comment saying it would
# query the tariff "once 0033 lands". It landed. #389 made registration its
# first consumer; these endpoints are how a facility maintains it.

# Tariff changes reprice every future invoice, so this is narrower than
# _BILLING_ROLES: a receptionist staffs the counter, they do not set prices.
_TARIFF_ADMIN_ROLES = ("supervisor", "admin")


@router.get(
    "/charge-master",
    response_model=list[TariffOut],
    summary="Tariff catalogue for the caller's facility",
)
async def list_tariffs(
    charge_code: str | None = Query(None, description="Filter to one charge_code."),
    active_only: bool = Query(True, description="Set false to include retired rows."),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_MIS_ROLES)),
) -> list[TariffOut]:
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    rows = await service.list_charge_master(
        db, facility_id, charge_code=charge_code, active_only=active_only
    )
    return [TariffOut.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/charge-master",
    response_model=TariffOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a tariff, closing the row it supersedes",
)
async def create_tariff(
    payload: TariffCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_TARIFF_ADMIN_ROLES)),
) -> TariffOut:
    """A price change is a NEW ROW, never an edit.

    Editing unit_price in place would silently rewrite what was charged on every
    invoice already raised against that row — invoice_items.charge_master_id
    would then point at a tariff that no longer says what the patient paid.
    """
    facility_id = await service.facility_id_for_user(db, keycloak_sub=user.sub)
    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=user.sub, fallback_id=getattr(user, "id", None)
    )
    try:
        tariff_id = await service.create_tariff(
            db,
            facility_id=facility_id,
            charge_code=payload.charge_code,
            description=payload.description,
            charge_category=payload.charge_category,
            unit_price=payload.unit_price,
            effective_from=payload.effective_from,
            scheme_code=payload.scheme_code,
            created_by=actor_id,
        )
    except service.TariffOverlap as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "tariff_overlap", "message": str(exc)},
        ) from exc

    rows = await service.list_charge_master(
        db, facility_id, charge_code=payload.charge_code, active_only=False
    )
    created = next(r for r in rows if r.id == tariff_id)
    return TariffOut.model_validate(created, from_attributes=True)


@router.post(
    "/charge-master/{tariff_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire a tariff (is_active = false; never deleted)",
)
async def deactivate_tariff(
    tariff_id: uuid.UUID,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_roles(*_TARIFF_ADMIN_ROLES)),
) -> None:
    """The row is kept: invoice_items.charge_master_id points at it, and a line
    whose tariff has vanished cannot be explained to a patient or an auditor."""
    actor_id = await service.resolve_actor_user_id(
        db, keycloak_sub=user.sub, fallback_id=getattr(user, "id", None)
    )
    if not await service.deactivate_tariff(
        db, tariff_id, updated_by=actor_id, facility_id=current_db_user.facility_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tariff not found or already inactive",
        )
