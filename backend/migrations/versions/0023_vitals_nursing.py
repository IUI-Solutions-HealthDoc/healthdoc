"""0023_vitals_nursing

Revision ID: 0023
Revises: 0022a
Create Date: 2026-08-11

Builds: vitals, nursing_handover_notes, intake_output_records,
        patient_movement_log (schema.md §3, migration 0023)

WHY THIS IS HERE AND NOT ON B3's BRANCH
---------------------------------------
0023 blocks 0024, and 0024 blocks Ajay's 0025 and 0027-0031 — six PRs that
have been written, reviewed and green for four days. No issue was ever
created for this migration: weeks 3-6 got API issues (#216 "IPD admission,
transfers, discharge summary API") but the schema underneath them was never
tracked, so nobody was assigned and nobody was late.

Transcribed from §3, not designed here. The SBAR shape of
nursing_handover_notes follows Aditya's draft on feature/w5-vitals-nursing
(29 July) — that branch ALTERed vitals rather than creating it, because it
assumed an 0018 that never merged, so the file could not be reused directly.

Chains off 0022a (dpdp_compliance), not 0022. Vani wrote 0021_dpdp_compliance
to the §2 plan while 0021 was being reassigned to Aditya's encounter_soap;
rather than send her to 0035 — which chains off the parked 0034 and would
have made a finished migration wait for the whole chain — she takes 0022a,
the same out-of-band convention as 0003a and 0020a-c.

app/nursing/ already exists as an empty package; models for these tables
belong there and are deliberately not added in this PR. Schema first so the
chain moves; the module can follow.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------------- vitals
    op.create_table(
        "vitals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        # Either an OPD encounter or an IPD admission, never neither — the
        # CHECK below enforces it. A vitals row that belongs to no clinical
        # context cannot be found again by anyone who needs it.
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("height_cm", sa.Numeric(5, 1), nullable=True),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=True),
        # bmi/whr are app-computed on write, never client-supplied (§3).
        sa.Column("bmi", sa.Numeric(4, 1), nullable=True),
        sa.Column("waist_cm", sa.Numeric(5, 1), nullable=True),
        sa.Column("hip_cm", sa.Numeric(5, 1), nullable=True),
        sa.Column("whr", sa.Numeric(3, 2), nullable=True),
        sa.Column("temp_c", sa.Numeric(3, 1), nullable=True),
        sa.Column("pulse_bpm", sa.Integer(), nullable=True),
        sa.Column("resp_rate", sa.Integer(), nullable=True),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("spo2_pct", sa.Integer(), nullable=True),
        sa.Column("pain_score", sa.SmallInteger(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "encounter_id IS NOT NULL OR admission_id IS NOT NULL",
            name="ck_vitals_encounter_or_admission",
        ),
    )
    # (patient_id, measured_at) not patient_id alone: every read of this
    # table is "this patient's vitals over time", and the trend view is the
    # whole point of structured capture.
    op.create_index("ix_vitals_patient_id_measured_at", "vitals",
                    ["patient_id", "measured_at"])

    # ------------------------------------------- nursing_handover_notes
    # SBAR (situation / background / assessment / recommendation) as four
    # columns rather than one free-text blob: NABH expects the structure,
    # and a handover that can't be read field-by-field at 3am isn't one.
    op.create_table(
        "nursing_handover_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shift", sa.String(30), nullable=False),
        sa.Column("situation", sa.Text(), nullable=True),
        sa.Column("background", sa.Text(), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("handed_over_to", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_nursing_handover_notes_admission_id",
                    "nursing_handover_notes", ["admission_id"])

    # ------------------------------------------- intake_output_records
    op.create_table(
        "intake_output_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "entry_type IN ('intake_oral','intake_iv','output_urine',"
            "'output_drain','output_other')",
            name="ck_intake_output_records_entry_type",
        ),
        # Direction lives in entry_type, so the volume is always positive.
        # A negative output would double-count against the balance.
        sa.CheckConstraint("volume_ml > 0",
                           name="ck_intake_output_records_volume_positive"),
    )
    op.create_index("ix_intake_output_records_admission_id_recorded_at",
                    "intake_output_records", ["admission_id", "recorded_at"])

    # -------------------------------------------- patient_movement_log
    # Append-only transfer trail. from_* are nullable because the first
    # movement is the admission itself — there is no ward to come from.
    op.create_table(
        "patient_movement_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_ward_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("from_bed_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("beds.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("to_ward_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("to_bed_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("moved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_patient_movement_log_admission_id_moved_at",
                    "patient_movement_log", ["admission_id", "moved_at"])


def downgrade() -> None:
    op.drop_index("ix_patient_movement_log_admission_id_moved_at",
                  table_name="patient_movement_log")
    op.drop_table("patient_movement_log")
    op.drop_index("ix_intake_output_records_admission_id_recorded_at",
                  table_name="intake_output_records")
    op.drop_table("intake_output_records")
    op.drop_index("ix_nursing_handover_notes_admission_id",
                  table_name="nursing_handover_notes")
    op.drop_table("nursing_handover_notes")
    op.drop_index("ix_vitals_patient_id_measured_at", table_name="vitals")
    op.drop_table("vitals")
