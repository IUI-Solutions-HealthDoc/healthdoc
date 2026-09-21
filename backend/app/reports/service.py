"""KPI production and executive operational reporting service (HD-26)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import update, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Bed, Ward
from app.billing.models import Invoice, Payment, Refund
from app.opd.models import Visit, Encounter
from app.orders.models import Order
from app.pathology.models import LabOrderItem, LabResult
from app.audit.models import AuditLog
from app.emergency.models import EmergencyTriage
from app.common.patient_scope import facility_timezone, facility_today
from app.reports.models import KpiSnapshot, TIMING_KPI_CODES, TIMING_KPI_VERSION
from app.reports.schemas import (
    EdCensusOut,
    KpiCatalogItem,
    KpiOut,
    ReceptionistSummaryOut,
)

KPI_CATALOG: list[KpiCatalogItem] = [
    KpiCatalogItem(
        kpi_code="OPD_REGISTRATIONS",
        name="OPD Registrations",
        category="opd",
        unit="count",
        description="Total outpatient registrations initiated in the period.",
        formula="COUNT(visits WHERE visit_type = 'opd')",
    ),
    KpiCatalogItem(
        kpi_code="OPD_VISITS",
        name="Completed Consultations",
        category="opd",
        unit="count",
        description="Total outpatient doctor consultations completed.",
        formula="COUNT(visits WHERE visit_type = 'opd' AND status = 'completed')",
    ),
    KpiCatalogItem(
        kpi_code="OPD_AVG_WAIT_MINS",
        name="Average OPD Wait Time",
        category="opd",
        unit="minutes",
        description="Average minutes from patient desk arrival to consultation start.",
        formula="AVG(consultation_started - registered_at)",
    ),
    KpiCatalogItem(
        kpi_code="ED_CENSUS",
        name="Emergency Department Census",
        category="emergency",
        unit="count",
        description="Total emergency encounters registered in the period.",
        formula="COUNT(visits WHERE visit_type = 'emergency')",
    ),
    KpiCatalogItem(
        kpi_code="ED_LWBS_RATE",
        name="Emergency LWBS Rate",
        category="emergency",
        unit="percent",
        description="Percentage of emergency patients who left without being seen.",
        formula="(COUNT(emergency visits with status = 'lwbs') / TOTAL emergency) * 100",
    ),
    KpiCatalogItem(
        kpi_code="BED_OCCUPANCY_RATE",
        name="Inpatient Bed Occupancy Rate",
        category="ipd",
        unit="percent",
        description="Percentage of active inpatient beds currently occupied.",
        formula="(Occupied Beds / Total Active Beds) * 100",
    ),
    KpiCatalogItem(
        kpi_code="LAB_TURNAROUND_HOURS",
        name="Laboratory Turnaround Time",
        category="lab",
        unit="hours",
        description="Mean elapsed hours from sample collection to verified result release.",
        formula="AVG(verified_at - collected_at)",
    ),
    KpiCatalogItem(
        kpi_code="REVENUE_COLLECTED",
        name="Net Revenue Collected",
        category="finance",
        unit="INR",
        description="Net cash/digital collections (payments minus refunds) in the period.",
        formula="SUM(payments.amount) - SUM(refunds.amount)",
    ),
]


async def produce_kpi_snapshots(
    db: AsyncSession,
    facility_id: uuid.UUID,
    period_start: date,
    period_end: date,
    kpi_codes: list[str] | None = None,
) -> list[KpiOut]:
    """Calculate and store idempotent closed-period KPI snapshots for a facility."""
    tz = await facility_timezone(db, facility_id)
    start_dt = datetime.combine(period_start, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_dt = datetime.combine(period_end, time.max, tzinfo=tz).astimezone(timezone.utc)

    target_codes = set(kpi_codes) if kpi_codes else {item.kpi_code for item in KPI_CATALOG}
    snapshots: list[KpiOut] = []

    # Keep old values for inspection, but invalidate their measurement claim
    # until the requested period has actual observations to recompute from.
    await db.execute(update(KpiSnapshot).where(KpiSnapshot.facility_id == facility_id,
        KpiSnapshot.period_start == period_start, KpiSnapshot.period_end == period_end,
        KpiSnapshot.kpi_code.in_(target_codes & TIMING_KPI_CODES)).values(calculation_version=None))

    # 1. OPD Registrations
    if "OPD_REGISTRATIONS" in target_codes:
        reg_count = (
            await db.execute(
                select(func.count(Visit.id)).where(
                    Visit.facility_id == facility_id,
                    Visit.visit_date >= start_dt,
                    Visit.visit_date <= end_dt,
                    Visit.visit_type == "opd",
                )
            )
        ).scalar_one() or 0
        snap = await _upsert_snapshot(
            db, facility_id, "OPD_REGISTRATIONS", period_start, period_end,
            Decimal(reg_count), Decimal(reg_count), None
        )
        snapshots.append(snap)

    # 2. OPD Completed Consultations
    if "OPD_VISITS" in target_codes:
        visits_count = (
            await db.execute(
                select(func.count(Visit.id)).where(
                    Visit.facility_id == facility_id,
                    Visit.visit_date >= start_dt,
                    Visit.visit_date <= end_dt,
                    Visit.visit_type == "opd",
                    Visit.status == "completed",
                )
            )
        ).scalar_one() or 0
        snap = await _upsert_snapshot(
            db, facility_id, "OPD_VISITS", period_start, period_end,
            Decimal(visits_count), Decimal(visits_count), None
        )
        snapshots.append(snap)

    # 3. OPD Average Wait Minutes
    if "OPD_AVG_WAIT_MINS" in target_codes:
        waits = await _opd_waits(db, facility_id, start_dt, end_dt)
        if waits:
            total = sum(waits, Decimal(0))
            snapshots.append(await _upsert_snapshot(db, facility_id, "OPD_AVG_WAIT_MINS",
                period_start, period_end, total / len(waits), total, Decimal(len(waits))))

    # 4. Emergency Department Census
    if "ED_CENSUS" in target_codes:
        ed_count = (
            await db.execute(
                select(func.count(Visit.id)).where(
                    Visit.facility_id == facility_id,
                    Visit.visit_date >= start_dt,
                    Visit.visit_date <= end_dt,
                    Visit.visit_type == "emergency",
                )
            )
        ).scalar_one() or 0
        snap = await _upsert_snapshot(
            db, facility_id, "ED_CENSUS", period_start, period_end,
            Decimal(ed_count), Decimal(ed_count), None
        )
        snapshots.append(snap)

    # 5. Emergency Left Without Being Seen (LWBS) Rate
    if "ED_LWBS_RATE" in target_codes:
        ed_total = (
            await db.execute(
                select(func.count(Visit.id)).where(
                    Visit.facility_id == facility_id,
                    Visit.visit_date >= start_dt,
                    Visit.visit_date <= end_dt,
                    Visit.visit_type == "emergency",
                )
            )
        ).scalar_one() or 0
        ed_lwbs = (
            await db.execute(
                select(func.count(Visit.id)).where(
                    Visit.facility_id == facility_id,
                    Visit.visit_date >= start_dt,
                    Visit.visit_date <= end_dt,
                    Visit.visit_type == "emergency",
                    Visit.status == "lwbs",
                )
            )
        ).scalar_one() or 0
        rate = Decimal(round((ed_lwbs / ed_total) * 100, 2)) if ed_total > 0 else Decimal("0.00")
        snap = await _upsert_snapshot(
            db, facility_id, "ED_LWBS_RATE", period_start, period_end,
            rate, Decimal(ed_lwbs), Decimal(ed_total)
        )
        snapshots.append(snap)

    # 6. Inpatient Bed Occupancy Rate
    if "BED_OCCUPANCY_RATE" in target_codes:
        beds_total = (
            await db.execute(
                select(func.count(Bed.id)).join(Ward, Ward.id == Bed.ward_id).where(
                    Ward.facility_id == facility_id,
                )
            )
        ).scalar_one() or 0
        beds_occupied = (
            await db.execute(
                select(func.count(Bed.id)).join(Ward, Ward.id == Bed.ward_id).where(
                    Ward.facility_id == facility_id,
                    Bed.status == "occupied",
                )
            )
        ).scalar_one() or 0
        occ_rate = Decimal(round((beds_occupied / beds_total) * 100, 2)) if beds_total > 0 else Decimal("0.00")
        snap = await _upsert_snapshot(
            db, facility_id, "BED_OCCUPANCY_RATE", period_start, period_end,
            occ_rate, Decimal(beds_occupied), Decimal(beds_total)
        )
        snapshots.append(snap)

    # 7. Laboratory Turnaround Hours
    if "LAB_TURNAROUND_HOURS" in target_codes:
        # The append-only verify audit event is authoritative: result.updated_at
        # can change again on amendment and must not stand in for release time.
        times = (await db.execute(
            select(LabOrderItem.collected_at, func.min(AuditLog.created_at))
            .join(LabResult, LabResult.lab_order_item_id == LabOrderItem.id)
            .join(Order, Order.id == LabOrderItem.order_id)
            .join(AuditLog, AuditLog.resource_id == LabResult.id)
            .where(Order.facility_id == facility_id, AuditLog.facility_id == facility_id,
                   AuditLog.resource_type == "lab_results", AuditLog.action == "verify",
                   LabOrderItem.collected_at.is_not(None))
            .group_by(LabOrderItem.id, LabOrderItem.collected_at)
        )).all()
        hours = [_elapsed(collected, verified, 3600) for collected, verified in times
                 if verified and start_dt <= _utc(verified) <= end_dt]
        hours = [duration for duration in hours if duration >= 0]
        if hours:
            total = sum(hours, Decimal(0))
            snapshots.append(await _upsert_snapshot(db, facility_id, "LAB_TURNAROUND_HOURS",
                period_start, period_end, total / len(hours), total, Decimal(len(hours))))

    # 8. Revenue Collected
    if "REVENUE_COLLECTED" in target_codes:
        payments_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Payment.amount), Decimal(0)))
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .where(
                    Invoice.facility_id == facility_id,
                    Payment.collected_at >= start_dt,
                    Payment.collected_at <= end_dt,
                    Payment.status == "success",
                )
            )
        ).scalar_one()
        refunds_sum = (
            await db.execute(
                select(func.coalesce(func.sum(Refund.amount), Decimal(0)))
                .join(Payment, Payment.id == Refund.payment_id)
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .where(
                    Invoice.facility_id == facility_id,
                    Refund.refunded_at >= start_dt,
                    Refund.refunded_at <= end_dt,
                )
            )
        ).scalar_one()
        net_revenue = Decimal(payments_sum) - Decimal(refunds_sum)
        snap = await _upsert_snapshot(
            db, facility_id, "REVENUE_COLLECTED", period_start, period_end,
            net_revenue, Decimal(payments_sum), Decimal(refunds_sum)
        )
        snapshots.append(snap)

    await db.flush()
    return snapshots


async def _upsert_snapshot(
    db: AsyncSession,
    facility_id: uuid.UUID,
    kpi_code: str,
    period_start: date,
    period_end: date,
    value: Decimal,
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> KpiOut:
    """Upsert a single KPI snapshot row."""
    existing = (
        await db.execute(
            select(KpiSnapshot).where(
                KpiSnapshot.facility_id == facility_id,
                KpiSnapshot.kpi_code == kpi_code,
                KpiSnapshot.period_start == period_start,
                KpiSnapshot.period_end == period_end,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.value = value
        existing.numerator = numerator
        existing.denominator = denominator
    else:
        existing = KpiSnapshot(
            id=uuid.uuid4(),
            facility_id=facility_id,
            kpi_code=kpi_code,
            period_start=period_start,
            period_end=period_end,
            value=value,
            numerator=numerator,
            denominator=denominator,
        )
        db.add(existing)

    existing.calculation_version = TIMING_KPI_VERSION if kpi_code in TIMING_KPI_CODES else None

    return KpiOut(
        kpi_code=kpi_code,
        period_start=period_start,
        period_end=period_end,
        value=value,
        numerator=numerator,
        denominator=denominator,
        calculation_version=existing.calculation_version,
    )


async def get_receptionist_summary(
    db: AsyncSession,
    facility_id: uuid.UUID,
    report_date: date,
) -> ReceptionistSummaryOut:
    """Live front-desk reception tracker for a given date."""
    tz = await facility_timezone(db, facility_id)
    start_dt = datetime.combine(report_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_dt = datetime.combine(report_date, time.max, tzinfo=tz).astimezone(timezone.utc)

    visits = (
        await db.execute(
            select(Visit).where(
                Visit.facility_id == facility_id,
                Visit.visit_date >= start_dt,
                Visit.visit_date <= end_dt,
                Visit.visit_type == "opd",
            )
        )
    ).scalars().all()

    total_registered = len(visits)
    waiting = sum(1 for v in visits if v.status in ("registered", "waiting", "in_queue"))
    in_consultation = sum(1 for v in visits if v.status == "in_consultation")
    completed = sum(1 for v in visits if v.status in ("completed", "closed", "discharged"))
    cancelled_or_lwbs = sum(1 for v in visits if v.status in ("cancelled", "lwbs"))

    waits = await _opd_waits(db, facility_id, start_dt, end_dt)
    avg_wait = float(sum(waits) / len(waits)) if waits else None

    return ReceptionistSummaryOut(
        facility_id=facility_id,
        report_date=report_date,
        total_registered=total_registered,
        waiting=waiting,
        in_consultation=in_consultation,
        completed=completed,
        cancelled_or_lwbs=cancelled_or_lwbs,
        average_wait_minutes=avg_wait,
    )


async def get_ed_census(
    db: AsyncSession,
    facility_id: uuid.UUID,
) -> EdCensusOut:
    """Live Emergency Department census and acuity breakdown."""
    today = await facility_today(db, facility_id)
    tz = await facility_timezone(db, facility_id)
    start_dt = datetime.combine(today, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_dt = datetime.combine(today, time.max, tzinfo=tz).astimezone(timezone.utc)

    ed_visits = (
        await db.execute(
            select(Visit).where(
                Visit.facility_id == facility_id,
                Visit.visit_date >= start_dt,
                Visit.visit_date <= end_dt,
                Visit.visit_type == "emergency",
            )
        )
    ).scalars().all()

    total_ed = len(ed_visits)
    active = sum(1 for v in ed_visits if v.status in ("registered", "in_consultation", "waiting", "triaged", "in_queue"))
    lwbs = sum(1 for v in ed_visits if v.status == "lwbs")

    admitted_count = (await db.execute(
        select(func.count(Admission.id)).join(Visit, Visit.id == Admission.visit_id).where(
            Visit.facility_id == facility_id, Visit.visit_type == "emergency",
            Admission.admitted_at >= start_dt, Admission.admitted_at <= end_dt,
            Admission.status == "admitted",
        )
    )).scalar_one() or 0
    acuity_rows = (await db.execute(
        select(EmergencyTriage.acuity_level, func.count(EmergencyTriage.id))
        .where(EmergencyTriage.facility_id == facility_id,
               EmergencyTriage.triaged_at >= start_dt, EmergencyTriage.triaged_at <= end_dt)
        .group_by(EmergencyTriage.acuity_level)
    )).all()
    acuity = dict(acuity_rows)

    return EdCensusOut(
        facility_id=facility_id,
        as_of=datetime.now(timezone.utc),
        total_emergency_today=total_ed,
        active_patients=active,
        lwbs_count=lwbs,
        admitted_to_ipd=admitted_count,
        triage_acuity_distribution=acuity,
    )

def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _elapsed(start: datetime, end: datetime, divisor: int) -> Decimal:
    return Decimal(str((_utc(end) - _utc(start)).total_seconds())) / divisor


async def _opd_waits(db: AsyncSession, facility_id: uuid.UUID,
                    start: datetime, end: datetime) -> list[Decimal]:
    rows = (await db.execute(
        select(Visit.visit_date, func.min(Encounter.started_at))
        .join(Encounter, Encounter.visit_id == Visit.id)
        .where(Visit.facility_id == facility_id, Encounter.facility_id == facility_id,
               Visit.visit_type == "opd", Visit.visit_date >= start, Visit.visit_date <= end,
               Encounter.started_at.is_not(None))
        .group_by(Visit.id, Visit.visit_date)
    )).all()
    return [_elapsed(arrival, seen, 60) for arrival, seen in rows
            if seen and _utc(seen) >= _utc(arrival)]
