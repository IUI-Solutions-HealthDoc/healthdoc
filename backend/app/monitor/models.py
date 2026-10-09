"""Control-room tables (migration 0097). See docs/control-room-design-2026-10-10.md."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class MonitorScope(Base, UUIDPk, Timestamps):
    """Which facilities a `monitor` may see: a whole state, or one district of it.

    Keyed by Keycloak subject, not users.id: a state or district officer belongs
    to no hospital, so has no users row (the same reason platform uses the JWT).
    """

    __tablename__ = "monitor_scopes"
    __table_args__ = (
        UniqueConstraint("keycloak_sub", "state_code", "district", name="uq_monitor_scopes_sub_area"),
        CheckConstraint("district IS NULL OR trim(district) <> ''", name="ck_monitor_scopes_district"),
        # NULL <> NULL: the unique constraint does not stop two whole-state grants.
        Index(
            "uq_monitor_scopes_sub_whole_state", "keycloak_sub", "state_code", unique=True,
            postgresql_where=text("district IS NULL"), sqlite_where=text("district IS NULL"),
        ),
    )

    keycloak_sub: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[str] = mapped_column(String(5), nullable=False)
    #: NULL means the whole state.
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    granted_by_sub: Mapped[str] = mapped_column(String(64), nullable=False)


class FacilityPulse(Base, UUIDPk):
    """One capture of a facility's live state, taken every 15 minutes.

    Counts only. Nothing here identifies a patient, so the board can be shown
    to an officer outside the facility without a care relationship.
    """

    __tablename__ = "facility_pulse"
    __table_args__ = (
        Index("ix_facility_pulse_facility_captured", "facility_id", "captured_at"),
        *(
            CheckConstraint(f"{name} >= 0", name=f"ck_facility_pulse_{name}")
            for name in (
                "opd_today", "queue_waiting", "emergency_open", "admitted_now", "beds_total",
                "lab_pending", "stock_below_reorder", "batches_expiring_30d", "staff_rostered_today",
            )
        ),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opd_today: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_waiting: Mapped[int] = mapped_column(Integer, nullable=False)
    emergency_open: Mapped[int] = mapped_column(Integer, nullable=False)
    admitted_now: Mapped[int] = mapped_column(Integer, nullable=False)
    beds_total: Mapped[int] = mapped_column(Integer, nullable=False)
    lab_pending: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_below_reorder: Mapped[int] = mapped_column(Integer, nullable=False)
    batches_expiring_30d: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_rostered_today: Mapped[int] = mapped_column(Integer, nullable=False)
    #: wards / stock_short / expiring, bounded lists, no patient data (0098).
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
