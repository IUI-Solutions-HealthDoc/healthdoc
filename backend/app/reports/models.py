"""SQLAlchemy models for reports and KPI snapshots (migration 0025)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint, or_
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk
from app.users.models import Facility  # noqa: F401


class KpiSnapshot(Base, UUIDPk, Timestamps):
    """The row 0025 created for closed-period hospital KPI metric commitments."""

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
    calculation_version: Mapped[str | None] = mapped_column(String(50), nullable=True)


TIMING_KPI_CODES = {"OPD_AVG_WAIT_MINS", "LAB_TURNAROUND_HOURS"}
TIMING_KPI_VERSION = "recorded_events_v1"


def verified_snapshot_filter():
    """Legacy timing values are untrusted until recomputed; other KPIs unchanged."""
    return or_(KpiSnapshot.kpi_code.not_in(TIMING_KPI_CODES),
               KpiSnapshot.calculation_version == TIMING_KPI_VERSION)
