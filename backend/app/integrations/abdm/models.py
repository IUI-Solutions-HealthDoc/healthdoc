"""ABDM module models (scan_share_tickets and ABDM M1 entities)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk


class ScanShareTicket(Base, UUIDPk, Timestamps):
    """ABDM M1 Scan-and-Share counter check-in tickets (0080)."""

    __tablename__ = "scan_share_tickets"

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    token_number: Mapped[str] = mapped_column(String(30), nullable=False)
    abha_address: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )
    counter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_scan_share_tickets_facility_id", "facility_id"),
        Index("ix_scan_share_tickets_patient_id", "patient_id"),
        Index("ix_scan_share_tickets_token_number", "token_number"),
        Index("ix_scan_share_tickets_abha_address", "abha_address"),
        Index("ix_scan_share_tickets_status", "status"),
    )
