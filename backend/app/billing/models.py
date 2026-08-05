"""Billing tariff catalogue — schema v3.14 §3 0033."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey

from app.common.db import Base
from app.common.enums import ChargeCategory
from app.common.models import Blame, Timestamps, UUIDPk


class ChargeMaster(Base, UUIDPk, Timestamps, Blame):
    """Effective-dated price catalogue.

    A price is NEVER updated in place — a revision inserts a new row with a later
    `effective_from`. That is what makes "what was the tariff on 12 March" answerable,
    which is the question an audit actually asks.
    """

    __tablename__ = "charge_master"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="ck_charge_master_unit_price_non_negative"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from",
                        name="ck_charge_master_effective_range"),
        CheckConstraint(ChargeCategory.sql_check("charge_category"),
                        name="ck_charge_master_charge_category"),
        UniqueConstraint("facility_id", "charge_code", "scheme_code", "effective_from",
                         name="uq_charge_master_version"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    charge_code: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    charge_category: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Decimal, never float — paise drift is unrecoverable (conventions §1.6).
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    #: NULL = general tariff. A scheme rate (PM-JAY) wins when the invoice carries it.
    scheme_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
