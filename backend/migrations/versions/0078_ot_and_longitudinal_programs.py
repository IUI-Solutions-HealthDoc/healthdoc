"""Operation Theatre lifecycle enhancements, WHO surgical safety checklist, and longitudinal care programs (HD-27, HD-28).

Revision ID: 0078
Revises: 0077
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- 1. HD-27: OPERATION THEATRE ENHANCEMENTS ----------------
    # ot_schedules: theatre_number, admission_id, pre_op_checklist, cancel_reason, surgical_safety_confirmed
    op.add_column(
        "ot_schedules",
        sa.Column("theatre_number", sa.String(50), nullable=False, server_default="OT-1"),
    )
    op.add_column(
        "ot_schedules",
        sa.Column(
            "admission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admissions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "ot_schedules",
        sa.Column("pre_op_checklist", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ot_schedules",
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "ot_schedules",
        sa.Column("surgical_safety_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_ot_schedules_admission_id", "ot_schedules", ["admission_id"])
    op.create_index("ix_ot_schedules_theatre_start", "ot_schedules", ["theatre_number", "scheduled_start"])

    # Update status constraint to include 'in_progress'
    op.drop_constraint("ck_ot_schedules_status", "ot_schedules", type_="check")
    op.create_check_constraint(
        "ck_ot_schedules_status",
        "ot_schedules",
        "status IN ('scheduled', 'in_progress', 'completed', 'cancelled')",
    )

    # ot_records: diagnosis, procedure details, anesthesia, nursing, safety verification
    op.add_column("ot_records", sa.Column("pre_op_diagnosis", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("post_op_diagnosis", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("procedure_performed", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("anesthesia_type", sa.String(50), nullable=True))
    op.add_column("ot_records", sa.Column("scrub_nurse", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("circulating_nurse", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("implants_used", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("ot_records", sa.Column("sponge_needle_count_correct", sa.Boolean(), nullable=True))
    op.add_column("ot_records", sa.Column("specimens_sent", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("ot_records", sa.Column("complications", sa.Text(), nullable=True))
    op.add_column("ot_records", sa.Column("recovery_status", sa.String(50), nullable=True))

    # ---------------- 2. HD-28: LONGITUDINAL CARE PROGRAMS ----------------
    op.create_table(
        "care_programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("program_code", sa.String(50), nullable=False, unique=True),
        sa.Column("program_name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="chronic"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_care_programs_program_code", "care_programs", ["program_code"])

    # Seed default programs
    op.execute(
        """
        INSERT INTO care_programs (program_code, program_name, category, description, is_active)
        VALUES
            ('DIABETES_T2', 'Type 2 Diabetes Mellitus Care Program', 'chronic', 'Comprehensive glycaemic monitoring, HbA1c tracking, renal and retinopathy surveillance.', true),
            ('HYPERTENSION', 'Essential Hypertension Care Program', 'chronic', 'Cardiovascular risk stratification, BP tracking, and end-organ protection surveillance.', true),
            ('ANC_MATERNAL', 'Antenatal & Maternal Longitudinal Care', 'maternal', 'Trimester tracking, fetal growth surveillance, high-risk screening, and immunization scheduling.', true),
            ('CKD_RENAL', 'Chronic Kidney Disease Care Program', 'chronic', 'eGFR progression monitoring, proteinuria tracking, and mineral metabolism surveillance.', true)
        ON CONFLICT (program_code) DO NOTHING;
        """
    )

    op.create_table(
        "program_enrolments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("program_code", sa.String(50), nullable=False),
        sa.Column("program_name", sa.String(100), nullable=False),
        sa.Column("enrolment_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("target_outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enrolled_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_program_enrolments_facility_id", "program_enrolments", ["facility_id"])
    op.create_index("ix_program_enrolments_patient_id", "program_enrolments", ["patient_id"])
    op.create_index("ix_program_enrolments_program_code", "program_enrolments", ["program_code"])
    op.create_index(
        "uq_active_program_enrolment",
        "program_enrolments",
        ["patient_id", "program_code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "program_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("enrolment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("program_enrolments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("clinical_summary", sa.Text(), nullable=True),
        sa.Column("conducted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_program_visits_enrolment_id", "program_visits", ["enrolment_id"])
    op.create_index("ix_program_visits_scheduled_date", "program_visits", ["scheduled_date"])


def downgrade() -> None:
    op.drop_index("ix_program_visits_scheduled_date", table_name="program_visits")
    op.drop_index("ix_program_visits_enrolment_id", table_name="program_visits")
    op.drop_table("program_visits")

    op.drop_index("uq_active_program_enrolment", table_name="program_enrolments")
    op.drop_index("ix_program_enrolments_program_code", table_name="program_enrolments")
    op.drop_index("ix_program_enrolments_patient_id", table_name="program_enrolments")
    op.drop_index("ix_program_enrolments_facility_id", table_name="program_enrolments")
    op.drop_table("program_enrolments")

    op.drop_index("ix_care_programs_program_code", table_name="care_programs")
    op.drop_table("care_programs")

    op.drop_column("ot_records", "recovery_status")
    op.drop_column("ot_records", "complications")
    op.drop_column("ot_records", "specimens_sent")
    op.drop_column("ot_records", "sponge_needle_count_correct")
    op.drop_column("ot_records", "implants_used")
    op.drop_column("ot_records", "circulating_nurse")
    op.drop_column("ot_records", "scrub_nurse")
    op.drop_column("ot_records", "anesthesia_type")
    op.drop_column("ot_records", "procedure_performed")
    op.drop_column("ot_records", "post_op_diagnosis")
    op.drop_column("ot_records", "pre_op_diagnosis")

    op.drop_constraint("ck_ot_schedules_status", "ot_schedules", type_="check")
    op.create_check_constraint(
        "ck_ot_schedules_status",
        "ot_schedules",
        "status IN ('scheduled','completed','cancelled')",
    )
    op.drop_index("ix_ot_schedules_theatre_start", table_name="ot_schedules")
    op.drop_index("ix_ot_schedules_admission_id", table_name="ot_schedules")
    op.drop_column("ot_schedules", "surgical_safety_confirmed")
    op.drop_column("ot_schedules", "cancel_reason")
    op.drop_column("ot_schedules", "pre_op_checklist")
    op.drop_column("ot_schedules", "admission_id")
    op.drop_column("ot_schedules", "theatre_number")
