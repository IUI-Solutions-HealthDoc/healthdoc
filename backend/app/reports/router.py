"""reports module — facility KPI snapshots (0025).

Was a ping stub: the last module in the product with no endpoints at all, while
`kpi_snapshots` has existed since migration 0025 with a unique key on
(facility_id, kpi_code, period_start, period_end).

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

This reads *stored snapshots*. It does not compute KPIs. That distinction is the
whole design:

  * Billing MIS (`/billing/mis/*`) computes live, because a cashier closing the
    till needs today's number and today is not yet a closed period.
  * A KPI snapshot is a value someone committed for a period that has ENDED.
    Recomputing it on read would silently change a figure a hospital may
    already have reported externally — an accreditation submission that moves
    when you reopen the screen is worse than no screen.

So there is no "recompute" endpoint here, and adding one is a decision about
who owns a published number, not a coding task.

Snapshots are written by whatever job owns each KPI; nothing in this module
writes them. That job does not exist yet — see the empty-state note on
`list_kpis`, which is honest about it rather than rendering zeros.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import Base, get_db
from app.common.models import Timestamps, UUIDPk

router = APIRouter(prefix="/reports", tags=["reports"])

# Same audience as billing MIS: this is a management view, not counter work.
_REPORT_ROLES = ("supervisor", "admin", "auditor")


class KpiSnapshot(Base, UUIDPk, Timestamps):
    """The row 0025 created and nothing mapped.

    One of the tables counted in the 96-vs-81 spec/ORM gap. That gap is not a
    documentation problem — an unmapped table is a feature nobody built.
    """

    __tablename__ = "kpi_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "facility_id", "kpi_code", "period_start", "period_end",
            name="uq_kpi_snapshots_facility_code_period",
        ),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    kpi_code: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    numerator: Mapped[Decimal | None] = mapped_column(Numeric)
    denominator: Mapped[Decimal | None] = mapped_column(Numeric)


class KpiOut(BaseModel):
    model_config = {"from_attributes": True}

    kpi_code: str
    period_start: date
    period_end: date
    value: Decimal
    #: Kept alongside `value` on purpose. "94%" is not reviewable; "47 of 50"
    #: is. A rate computed over a denominator of 3 looks identical to one over
    #: 3,000 until you can see it.
    numerator: Decimal | None
    denominator: Decimal | None


class KpiListOut(BaseModel):
    items: list[KpiOut]
    period_start: date
    period_end: date
    #: True when the facility has no snapshots in this window at all. The screen
    #: must say "not yet computed" rather than draw an empty chart, which reads
    #: as "zero" — a very different clinical and financial claim.
    no_snapshots: bool


def _window(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Resolve the requested window.

    Explicit dates win. Otherwise `period` gives a trailing window ending today
    — trailing rather than calendar-aligned, because a hospital asking for
    "this month" on the 3rd wants the last 30 days, not three days of data
    presented as a month.
    """
    if date_from and date_to:
        return date_from, date_to

    today = date.today()
    spans = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}
    return today - timedelta(days=spans.get(period, 30)), today


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
    return {"module": "reports", "status": "ok"}


@router.get(
    "/kpis",
    response_model=KpiListOut,
    dependencies=[Depends(require_roles(*_REPORT_ROLES))],
)
async def list_kpis(
    current_db_user: CurrentDbUser,
    period: str = Query("monthly", description="daily | weekly | monthly | quarterly | yearly"),
    date_from: date | None = None,
    date_to: date | None = None,
    kpi_code: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> KpiListOut:
    """Stored KPI snapshots for this facility, within a window.

    Facility-scoped from the token; `kpi_snapshots.facility_id` is a real column
    so no join is needed, unlike most of the compliance reads.

    A snapshot overlaps the window if it starts before the window ends AND ends
    after the window starts. Overlap rather than containment: a monthly snapshot
    is genuinely part of a quarter's picture, and requiring full containment
    would drop it from every window that does not align to its boundaries.

    `no_snapshots` is returned rather than left for the client to infer from an
    empty list, because those are different states. No snapshot means nobody has
    computed the figure yet — the writer job does not exist. Zero would mean the
    figure was computed and came out zero. A dashboard that renders one as the
    other tells a hospital its infection rate is nil when in fact nothing has
    ever measured it.
    """
    start, end = _window(period, date_from, date_to)

    query = select(KpiSnapshot).where(
        KpiSnapshot.facility_id == current_db_user.facility_id,
        KpiSnapshot.period_start <= end,
        KpiSnapshot.period_end >= start,
    )
    if kpi_code:
        query = query.where(KpiSnapshot.kpi_code == kpi_code)

    rows = (
        (
            await db.execute(
                query.order_by(KpiSnapshot.period_start.desc(), KpiSnapshot.kpi_code)
            )
        )
        .scalars()
        .all()
    )

    return KpiListOut(
        items=[KpiOut.model_validate(row) for row in rows],
        period_start=start,
        period_end=end,
        no_snapshots=len(rows) == 0,
    )


@router.get(
    "/kpis/codes",
    dependencies=[Depends(require_roles(*_REPORT_ROLES))],
)
async def list_kpi_codes(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Which KPI codes this facility actually has snapshots for.

    Derived from the data rather than from a hardcoded catalogue: a fixed list
    would show a hospital metrics nobody computes for it, and every one of those
    would render as an empty chart indistinguishable from a real zero.
    """
    rows = (
        (
            await db.execute(
                select(KpiSnapshot.kpi_code)
                .where(KpiSnapshot.facility_id == current_db_user.facility_id)
                .distinct()
                .order_by(KpiSnapshot.kpi_code)
            )
        )
        .scalars()
        .all()
    )
    return {"items": list(rows)}
