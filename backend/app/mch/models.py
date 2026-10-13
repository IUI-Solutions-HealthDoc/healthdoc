"""Maternal and child health records (migration 0103).

Record only, by owner decision (10 Oct 2026): HealthDoc stores what clinicians
observe and decide. It computes no visit schedule, due date or "overdue" flag,
and "high risk" is a clinician's flag with a reason, never inferred, because
those are clinical rules nobody has approved for this system.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base
from app.common.models import Timestamps, UUIDPk

PREGNANCY_STATUSES = ("active", "delivered", "ended")
DELIVERY_MODES = ("normal", "assisted", "caesarean")
BIRTH_OUTCOMES = ("live_birth", "still_birth")


def _fk(table: str, nullable: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable)


class Pregnancy(Base, UUIDPk, Timestamps):
    __tablename__ = "mch_pregnancies"
    __audit_resource_type__ = "mch_pregnancies"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'delivered', 'ended')", name="ck_mch_pregnancies_status"),
        CheckConstraint("gravida IS NULL OR gravida BETWEEN 1 AND 20", name="ck_mch_pregnancies_gravida"),
        CheckConstraint("para IS NULL OR para BETWEEN 0 AND 20", name="ck_mch_pregnancies_para"),
        CheckConstraint(
            "NOT high_risk OR (high_risk_reason IS NOT NULL AND trim(high_risk_reason) <> '')",
            name="ck_mch_pregnancies_high_risk_reason",
        ),
        CheckConstraint(
            "status <> 'ended' OR (end_reason IS NOT NULL AND trim(end_reason) <> '')",
            name="ck_mch_pregnancies_end_reason",
        ),
        Index("ix_mch_pregnancies_facility_status", "facility_id", "status"),
        Index("ix_mch_pregnancies_patient_id", "patient_id"),
        Index("ix_mch_pregnancies_created_by", "created_by"),
        # One open pregnancy per patient per facility; the clinician closes it first.
        Index(
            "uq_mch_pregnancies_one_active", "facility_id", "patient_id", unique=True,
            postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'"),
        ),
    )

    facility_id: Mapped[uuid.UUID] = _fk("facilities")
    patient_id: Mapped[uuid.UUID] = _fk("patients")
    lmp_date: Mapped[date | None] = mapped_column(Date)
    #: As the clinician records it; HealthDoc does not compute it.
    edd: Mapped[date | None] = mapped_column(Date)
    gravida: Mapped[int | None] = mapped_column(Integer)
    para: Mapped[int | None] = mapped_column(Integer)
    #: The state Reproductive and Child Health portal id, when one exists.
    rch_id: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    high_risk_reason: Mapped[str | None] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = _fk("users")


class AncVisit(Base, UUIDPk, Timestamps):
    __tablename__ = "mch_anc_visits"
    __audit_resource_type__ = "mch_anc_visits"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        # Plausibility bounds catch a mistyped value; they are not clinical thresholds.
        CheckConstraint("gestation_weeks IS NULL OR gestation_weeks BETWEEN 1 AND 45", name="ck_mch_anc_gestation"),
        CheckConstraint("weight_kg IS NULL OR weight_kg BETWEEN 20 AND 250", name="ck_mch_anc_weight"),
        CheckConstraint("bp_systolic IS NULL OR bp_systolic BETWEEN 50 AND 260", name="ck_mch_anc_bp_sys"),
        CheckConstraint("bp_diastolic IS NULL OR bp_diastolic BETWEEN 20 AND 180", name="ck_mch_anc_bp_dia"),
        CheckConstraint("hemoglobin_g_dl IS NULL OR hemoglobin_g_dl BETWEEN 2 AND 22", name="ck_mch_anc_hb"),
        CheckConstraint("fundal_height_cm IS NULL OR fundal_height_cm BETWEEN 5 AND 50", name="ck_mch_anc_fundal"),
        CheckConstraint("fetal_heart_rate IS NULL OR fetal_heart_rate BETWEEN 50 AND 240", name="ck_mch_anc_fhr"),
        CheckConstraint("ifa_tablets IS NULL OR ifa_tablets BETWEEN 0 AND 400", name="ck_mch_anc_ifa"),
        Index("ix_mch_anc_visits_pregnancy", "pregnancy_id", "visit_date"),
        Index("ix_mch_anc_visits_facility_date", "facility_id", "visit_date"),
        Index("ix_mch_anc_visits_recorded_by", "recorded_by"),
    )

    pregnancy_id: Mapped[uuid.UUID] = _fk("mch_pregnancies")
    facility_id: Mapped[uuid.UUID] = _fk("facilities")
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    gestation_weeks: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    bp_systolic: Mapped[int | None] = mapped_column(Integer)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer)
    hemoglobin_g_dl: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    fundal_height_cm: Mapped[int | None] = mapped_column(Integer)
    fetal_heart_rate: Mapped[int | None] = mapped_column(Integer)
    urine_albumin: Mapped[str | None] = mapped_column(String(50))
    urine_sugar: Mapped[str | None] = mapped_column(String(50))
    ifa_tablets: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = _fk("users")


class Delivery(Base, UUIDPk, Timestamps):
    __tablename__ = "mch_deliveries"
    __audit_resource_type__ = "mch_deliveries"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        UniqueConstraint("pregnancy_id", name="uq_mch_deliveries_pregnancy"),
        CheckConstraint("mode IN ('normal', 'assisted', 'caesarean')", name="ck_mch_deliveries_mode"),
        Index("ix_mch_deliveries_facility_at", "facility_id", "delivered_at"),
        Index("ix_mch_deliveries_recorded_by", "recorded_by"),
    )

    pregnancy_id: Mapped[uuid.UUID] = _fk("mch_pregnancies")
    facility_id: Mapped[uuid.UUID] = _fk("facilities")
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = _fk("users")


class Newborn(Base, UUIDPk, Timestamps):
    __tablename__ = "mch_newborns"
    __audit_resource_type__ = "mch_newborns"
    __audit_facility_id_field__ = "facility_id"
    __table_args__ = (
        CheckConstraint("outcome IN ('live_birth', 'still_birth')", name="ck_mch_newborns_outcome"),
        CheckConstraint("sex IN ('male', 'female', 'other', 'unknown')", name="ck_mch_newborns_sex"),
        CheckConstraint("birth_weight_g IS NULL OR birth_weight_g BETWEEN 200 AND 7000", name="ck_mch_newborns_weight"),
        Index("ix_mch_newborns_delivery", "delivery_id"),
        Index("ix_mch_newborns_facility_id", "facility_id"),
        Index("ix_mch_newborns_patient_id", "patient_id"),
    )

    delivery_id: Mapped[uuid.UUID] = _fk("mch_deliveries")
    facility_id: Mapped[uuid.UUID] = _fk("facilities")
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    sex: Mapped[str] = mapped_column(String(50), nullable=False)
    birth_weight_g: Mapped[int | None] = mapped_column(Integer)
    #: The baby's own chart, once registered.
    patient_id: Mapped[uuid.UUID | None] = _fk("patients", nullable=True)

