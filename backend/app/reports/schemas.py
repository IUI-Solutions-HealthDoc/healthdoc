"""Pydantic schemas for reports, KPI production, and operational tracking (HD-26)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class KpiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kpi_code: str
    period_start: date
    period_end: date
    value: Decimal
    numerator: Decimal | None = None
    denominator: Decimal | None = None


class KpiListOut(BaseModel):
    items: list[KpiOut]
    period_start: date
    period_end: date
    no_snapshots: bool


class KpiProduceRequest(BaseModel):
    period_start: date
    period_end: date
    kpi_codes: list[str] | None = Field(
        default=None,
        description="Optional subset of KPI codes to compute; computes all when None.",
    )


class KpiProduceResponse(BaseModel):
    facility_id: uuid.UUID
    period_start: date
    period_end: date
    snapshots_created: int
    items: list[KpiOut]


class KpiCatalogItem(BaseModel):
    kpi_code: str
    name: str
    category: str
    unit: str
    description: str
    formula: str


class ReceptionistSummaryOut(BaseModel):
    facility_id: uuid.UUID
    report_date: date
    total_registered: int
    waiting: int
    in_consultation: int
    completed: int
    cancelled_or_lwbs: int
    average_wait_minutes: float


class EdCensusOut(BaseModel):
    facility_id: uuid.UUID
    as_of: datetime
    total_emergency_today: int
    active_patients: int
    lwbs_count: int
    admitted_to_ipd: int
    triage_acuity_distribution: dict[str, int]
