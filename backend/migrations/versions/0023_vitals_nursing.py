"""0023_vitals_nursing

Revision ID: 0023
Revises: 0021
Create Date: 2026-07-28 05:07:38.943457

Reconciles the `vitals` table (created in 0018 with different column
names/shape) with the current app.opd.models.Vitals ORM model, and adds
the two new nursing tables (handover notes, intake/output).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0023'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Reconcile vitals table with current model ---

    # encounter_id must become nullable: a vitals row can now belong to
    # either an encounter (OPD) or an admission (IPD), not only an encounter.
    op.alter_column("vitals", "encounter_id", nullable=True)

    # Add admission_id (nullable FK) and patient_id (nullable for now,
    # backfilled below, then set NOT NULL).
    op.add_column(
        "vitals",
        sa.Column("admission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admissions.id"), nullable=True),
    )
    op.add_column(
        "vitals",
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=True),
    )

    # Rename existing columns to match the current model's field names.
    op.alter_column("vitals", "pulse", new_column_name="pulse_bpm")
    op.alter_column("vitals", "spo2", new_column_name="spo2_pct")
    op.alter_column("vitals", "respiratory_rate", new_column_name="resp_rate")
    op.alter_column("vitals", "weight", new_column_name="weight_kg")
    op.alter_column("vitals", "recorded_at", new_column_name="measured_at")
    op.alter_column("vitals", "recorded_by", new_column_name="created_by")

    # temperature -> temp_c: rename + narrow precision to match model (3,1)
    op.alter_column(
        "vitals", "temperature",
        new_column_name="temp_c",
        type_=sa.Numeric(3, 1),
    )
    # height -> height_cm: rename + adjust precision to match model (5,1)
    op.alter_column(
        "vitals", "height",
        new_column_name="height_cm",
        type_=sa.Numeric(5, 1),
    )

    # New app-computed and additional clinical columns.
    op.add_column("vitals", sa.Column("bmi", sa.Numeric(4, 1), nullable=True))
    op.add_column("vitals", sa.Column("waist_cm", sa.Numeric(5, 1), nullable=True))
    op.add_column("vitals", sa.Column("hip_cm", sa.Numeric(5, 1), nullable=True))
    op.add_column("vitals", sa.Column("whr", sa.Numeric(3, 2), nullable=True))
    op.add_column("vitals", sa.Column("pain_score", sa.Integer(), nullable=True))
    op.add_column(
        "vitals",
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )

    # Backfill patient_id for any existing rows via encounters -> visits.
    op.execute(
        """
        UPDATE vitals
        SET patient_id = visits.patient_id
        FROM encounters
        JOIN visits ON encounters.visit_id = visits.id
        WHERE vitals.encounter_id = encounters.id
          AND vitals.patient_id IS NULL
        """
    )
    op.alter_column("vitals", "patient_id", nullable=False)

    # Replace old spo2 check constraint (referenced old column name) with
    # one on the renamed column, and add the encounter-or-admission rule.
    op.drop_constraint("ck_vitals_spo2_range", "vitals", type_="check")
    op.create_check_constraint(
        "ck_vitals_spo2_range", "vitals", "spo2_pct IS NULL OR (spo2_pct >= 0 AND spo2_pct <= 100)"
    )
    op.create_check_constraint(
        "ck_vitals_encounter_or_admission", "vitals", "encounter_id IS NOT NULL OR admission_id IS NOT NULL"
    )

    # --- New nursing tables ---

    op.create_table(
        "nursing_handover_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admissions.id"), nullable=False),
        sa.Column("shift", sa.String(50), nullable=False),
        sa.Column("situation", sa.Text(), nullable=True),
        sa.Column("background", sa.Text(), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("handed_over_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("shift IN ('morning', 'evening', 'night')", name="ck_nursing_handover_notes_shift"),
    )
    op.create_index("ix_nursing_handover_notes_admission_id", "nursing_handover_notes", ["admission_id"])
    op.create_index("ix_nursing_handover_notes_handed_over_to", "nursing_handover_notes", ["handed_over_to"])

    op.create_table(
        "intake_output_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admissions.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "entry_type IN ('intake_oral', 'intake_iv', 'output_urine', 'output_drain', 'output_other')",
            name="ck_intake_output_records_entry_type",
        ),
        sa.CheckConstraint("volume_ml > 0", name="ck_intake_output_records_volume_positive"),
    )
    op.create_index("ix_intake_output_records_admission_id", "intake_output_records", ["admission_id"])


def downgrade() -> None:
    op.drop_index("ix_intake_output_records_admission_id", table_name="intake_output_records")
    op.drop_table("intake_output_records")

    op.drop_index("ix_nursing_handover_notes_handed_over_to", table_name="nursing_handover_notes")
    op.drop_index("ix_nursing_handover_notes_admission_id", table_name="nursing_handover_notes")
    op.drop_table("nursing_handover_notes")

    op.drop_constraint("ck_vitals_encounter_or_admission", "vitals", type_="check")
    op.drop_constraint("ck_vitals_spo2_range", "vitals", type_="check")
    op.create_check_constraint(
        "ck_vitals_spo2_range", "vitals", "spo2_pct IS NULL OR (spo2_pct >= 0 AND spo2_pct <= 100)"
    )

    op.drop_column("vitals", "updated_by")
    op.drop_column("vitals", "pain_score")
    op.drop_column("vitals", "whr")
    op.drop_column("vitals", "hip_cm")
    op.drop_column("vitals", "waist_cm")
    op.drop_column("vitals", "bmi")

    op.alter_column("vitals", "height_cm", new_column_name="height", type_=sa.Numeric(5, 2))
    op.alter_column("vitals", "temp_c", new_column_name="temperature", type_=sa.Numeric(4, 1))
    op.alter_column("vitals", "created_by", new_column_name="recorded_by")
    op.alter_column("vitals", "measured_at", new_column_name="recorded_at")
    op.alter_column("vitals", "weight_kg", new_column_name="weight")
    op.alter_column("vitals", "resp_rate", new_column_name="respiratory_rate")
    op.alter_column("vitals", "spo2_pct", new_column_name="spo2")
    op.alter_column("vitals", "pulse_bpm", new_column_name="pulse")

    op.drop_column("vitals", "patient_id")
    op.drop_column("vitals", "admission_id")
    op.alter_column("vitals", "encounter_id", nullable=False)
