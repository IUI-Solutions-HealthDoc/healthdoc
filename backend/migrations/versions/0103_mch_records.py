"""Maternal and child health records: pregnancies, ANC visits, deliveries, newborns.

Revision ID: 0103
Revises: 0102
Create Date: 2026-10-10

Record only (owner decision, 10 Oct 2026): what clinicians observe and decide.
No schedule, computed due date or overdue flag; "high risk" is a clinician's
flag with a reason. Range checks catch mistyped values and are not clinical
thresholds. The control room counts these per facility; it never sees a name.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mch_pregnancies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lmp_date", sa.Date(), nullable=True),
        sa.Column("edd", sa.Date(), nullable=True),
        sa.Column("gravida", sa.Integer(), nullable=True),
        sa.Column("para", sa.Integer(), nullable=True),
        sa.Column("rch_id", sa.String(30), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("high_risk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("high_risk_reason", sa.Text(), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'delivered', 'ended')", name="ck_mch_pregnancies_status"),
        sa.CheckConstraint("gravida IS NULL OR gravida BETWEEN 1 AND 20", name="ck_mch_pregnancies_gravida"),
        sa.CheckConstraint("para IS NULL OR para BETWEEN 0 AND 20", name="ck_mch_pregnancies_para"),
        sa.CheckConstraint(
            "NOT high_risk OR (high_risk_reason IS NOT NULL AND trim(high_risk_reason) <> '')",
            name="ck_mch_pregnancies_high_risk_reason",
        ),
        sa.CheckConstraint(
            "status <> 'ended' OR (end_reason IS NOT NULL AND trim(end_reason) <> '')",
            name="ck_mch_pregnancies_end_reason",
        ),
    )
    op.create_index("ix_mch_pregnancies_facility_status", "mch_pregnancies", ["facility_id", "status"])
    op.create_index("ix_mch_pregnancies_patient_id", "mch_pregnancies", ["patient_id"])
    op.create_index("ix_mch_pregnancies_created_by", "mch_pregnancies", ["created_by"])
    op.create_index(
        "uq_mch_pregnancies_one_active", "mch_pregnancies", ["facility_id", "patient_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "mch_anc_visits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("pregnancy_id", UUID(as_uuid=True), sa.ForeignKey("mch_pregnancies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("gestation_weeks", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(5, 1), nullable=True),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("hemoglobin_g_dl", sa.Numeric(4, 1), nullable=True),
        sa.Column("fundal_height_cm", sa.Integer(), nullable=True),
        sa.Column("fetal_heart_rate", sa.Integer(), nullable=True),
        sa.Column("urine_albumin", sa.String(50), nullable=True),
        sa.Column("urine_sugar", sa.String(50), nullable=True),
        sa.Column("ifa_tablets", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("gestation_weeks IS NULL OR gestation_weeks BETWEEN 1 AND 45", name="ck_mch_anc_gestation"),
        sa.CheckConstraint("weight_kg IS NULL OR weight_kg BETWEEN 20 AND 250", name="ck_mch_anc_weight"),
        sa.CheckConstraint("bp_systolic IS NULL OR bp_systolic BETWEEN 50 AND 260", name="ck_mch_anc_bp_sys"),
        sa.CheckConstraint("bp_diastolic IS NULL OR bp_diastolic BETWEEN 20 AND 180", name="ck_mch_anc_bp_dia"),
        sa.CheckConstraint("hemoglobin_g_dl IS NULL OR hemoglobin_g_dl BETWEEN 2 AND 22", name="ck_mch_anc_hb"),
        sa.CheckConstraint("fundal_height_cm IS NULL OR fundal_height_cm BETWEEN 5 AND 50", name="ck_mch_anc_fundal"),
        sa.CheckConstraint("fetal_heart_rate IS NULL OR fetal_heart_rate BETWEEN 50 AND 240", name="ck_mch_anc_fhr"),
        sa.CheckConstraint("ifa_tablets IS NULL OR ifa_tablets BETWEEN 0 AND 400", name="ck_mch_anc_ifa"),
    )
    op.create_index("ix_mch_anc_visits_pregnancy", "mch_anc_visits", ["pregnancy_id", "visit_date"])
    op.create_index("ix_mch_anc_visits_facility_date", "mch_anc_visits", ["facility_id", "visit_date"])
    op.create_index("ix_mch_anc_visits_recorded_by", "mch_anc_visits", ["recorded_by"])

    op.create_table(
        "mch_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("pregnancy_id", UUID(as_uuid=True), sa.ForeignKey("mch_pregnancies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pregnancy_id", name="uq_mch_deliveries_pregnancy"),
        sa.CheckConstraint("mode IN ('normal', 'assisted', 'caesarean')", name="ck_mch_deliveries_mode"),
    )
    op.create_index("ix_mch_deliveries_facility_at", "mch_deliveries", ["facility_id", "delivered_at"])
    op.create_index("ix_mch_deliveries_recorded_by", "mch_deliveries", ["recorded_by"])

    op.create_table(
        "mch_newborns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("delivery_id", UUID(as_uuid=True), sa.ForeignKey("mch_deliveries.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("sex", sa.String(50), nullable=False),
        sa.Column("birth_weight_g", sa.Integer(), nullable=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("outcome IN ('live_birth', 'still_birth')", name="ck_mch_newborns_outcome"),
        sa.CheckConstraint("sex IN ('male', 'female', 'other', 'unknown')", name="ck_mch_newborns_sex"),
        sa.CheckConstraint("birth_weight_g IS NULL OR birth_weight_g BETWEEN 200 AND 7000", name="ck_mch_newborns_weight"),
    )
    op.create_index("ix_mch_newborns_delivery", "mch_newborns", ["delivery_id"])
    op.create_index("ix_mch_newborns_facility_id", "mch_newborns", ["facility_id"])
    op.create_index("ix_mch_newborns_patient_id", "mch_newborns", ["patient_id"])


def downgrade() -> None:
    for table in ("mch_newborns", "mch_deliveries", "mch_anc_visits", "mch_pregnancies"):
        op.drop_table(table)
