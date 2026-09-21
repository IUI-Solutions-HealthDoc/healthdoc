"""reports module — facility KPI snapshots, production engine, and operational summaries (0025, HD-26)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, require_roles
from app.common.db import get_db
from app.reports.models import KpiSnapshot, verified_snapshot_filter
from app.common.patient_scope import facility_today
from app.reports.schemas import (
    EdCensusOut,
    KpiCatalogItem,
    KpiListOut,
    KpiOut,
    KpiProduceRequest,
    KpiProduceResponse,
    ReceptionistSummaryOut,
)
from app.reports.service import KPI_CATALOG, get_ed_census, get_receptionist_summary, produce_kpi_snapshots

router = APIRouter(prefix="/reports", tags=["reports"])

# Same audience as billing MIS: this is a management view, not counter work.
_REPORT_ROLES = ("supervisor", "admin", "auditor", "receptionist", "doctor", "nurse", "billing")


def _window(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Resolve the requested window."""
    if date_from and date_to:
        return date_from, date_to

    today = date.today()
    spans = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}
    return today - timedelta(days=spans.get(period, 30)), today


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
    """Stored KPI snapshots for this facility, within a window."""
    start, end = _window(period, date_from, date_to)

    query = select(KpiSnapshot).where(
        KpiSnapshot.facility_id == current_db_user.facility_id,
        KpiSnapshot.period_start <= end,
        KpiSnapshot.period_end >= start,
        verified_snapshot_filter(),
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
    """Which KPI codes this facility actually has snapshots for."""
    rows = (
        (
            await db.execute(
                select(KpiSnapshot.kpi_code)
                .where(KpiSnapshot.facility_id == current_db_user.facility_id, verified_snapshot_filter())
                .distinct()
                .order_by(KpiSnapshot.kpi_code)
            )
        )
        .scalars()
        .all()
    )
    return {"items": list(rows)}


@router.get(
    "/kpis/catalog",
    response_model=list[KpiCatalogItem],
    dependencies=[Depends(require_roles(*_REPORT_ROLES))],
)
async def get_kpi_catalog() -> list[KpiCatalogItem]:
    """Return standard catalog of KPIs computed by the publication engine."""
    return KPI_CATALOG


@router.post(
    "/kpis/produce",
    response_model=KpiProduceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("supervisor", "admin"))],
)
async def produce_kpis(
    body: KpiProduceRequest,
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> KpiProduceResponse:
    """Calculate and store idempotent closed-period KPI snapshots for this facility."""
    snapshots = await produce_kpi_snapshots(
        db=db,
        facility_id=current_db_user.facility_id,
        period_start=body.period_start,
        period_end=body.period_end,
        kpi_codes=body.kpi_codes,
    )
    await db.commit()
    return KpiProduceResponse(
        facility_id=current_db_user.facility_id,
        period_start=body.period_start,
        period_end=body.period_end,
        snapshots_created=len(snapshots),
        items=snapshots,
    )


@router.get(
    "/receptionist-summary",
    response_model=ReceptionistSummaryOut,
    dependencies=[Depends(require_roles(*_REPORT_ROLES))],
)
async def get_receptionist_tracker(
    current_db_user: CurrentDbUser,
    for_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> ReceptionistSummaryOut:
    """Live front desk OPD queue tracker and wait-time metrics for today."""
    target_date = for_date or await facility_today(db, current_db_user.facility_id)
    return await get_receptionist_summary(
        db=db,
        facility_id=current_db_user.facility_id,
        report_date=target_date,
    )


@router.get(
    "/ed-census",
    response_model=EdCensusOut,
    dependencies=[Depends(require_roles(*_REPORT_ROLES))],
)
async def get_live_ed_census(
    current_db_user: CurrentDbUser,
    db: AsyncSession = Depends(get_db),
) -> EdCensusOut:
    """Live Emergency Department census, active counts, and triage acuity distribution."""
    return await get_ed_census(
        db=db,
        facility_id=current_db_user.facility_id,
    )
