"""Suite 8: Immunization, blood bank crossmatch, configurable forms, order sets, safe outbox DLQ, and direct-service visits (HD-29 to HD-32).

Revision ID: 0079
Revises: 0078
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

_VISIT_TYPE_OLD = "'opd'::character varying, 'ipd'::character varying, 'day_care'::character varying, 'emergency'::character varying, 'teleconsult'::character varying"
_VISIT_TYPE_NEW = "'opd'::character varying, 'ipd'::character varying, 'day_care'::character varying, 'emergency'::character varying, 'teleconsult'::character varying, 'direct_service'::character varying"
_VISIT_CONSTRAINT = "ck_visits_ck_visits_visit_type"


def upgrade() -> None:
    # ---------------- 1. HD-29: IMMUNIZATION LIFECYCLE ----------------
    op.create_table(
        "vaccine_catalogue",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("target_disease", sa.String(200), nullable=False),
        sa.Column("standard_doses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_age_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_age_days", sa.Integer(), nullable=True),
        sa.Column("route", sa.String(50), nullable=False, server_default="intramuscular"),
        sa.Column("site", sa.String(50), nullable=False, server_default="left_upper_arm"),
        sa.Column("dose_quantity", sa.String(50), nullable=False, server_default="0.5 ml"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "immunization_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vaccine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vaccine_catalogue.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vaccine_code", sa.String(50), nullable=False),
        sa.Column("dose_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("administered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("batch_number", sa.String(50), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("manufacturer", sa.String(100), nullable=True),
        sa.Column("site", sa.String(50), nullable=True),
        sa.Column("route", sa.String(50), nullable=True),
        sa.Column("administered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("adverse_reaction", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_immunization_records_patient_id", "immunization_records", ["patient_id"])
    op.create_index("ix_immunization_records_vaccine_id", "immunization_records", ["vaccine_id"])
    op.create_index("ix_immunization_records_vaccine_code", "immunization_records", ["vaccine_code"])
    op.create_index("ix_immunization_records_administered_by", "immunization_records", ["administered_by"])

    # ---------------- 2. HD-29: BLOOD BANK CROSSMATCHES ----------------
    op.create_table(
        "blood_crossmatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("request_id", sa.String(50), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("blood_units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("compatibility_result", sa.String(50), nullable=False, server_default="compatible"),
        sa.Column("crossmatched_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("crossmatched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adverse_reactions", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_blood_crossmatches_request_id", "blood_crossmatches", ["request_id"])
    op.create_index("ix_blood_crossmatches_patient_id", "blood_crossmatches", ["patient_id"])
    op.create_index("ix_blood_crossmatches_unit_id", "blood_crossmatches", ["unit_id"])
    op.create_index("ix_blood_crossmatches_crossmatched_by", "blood_crossmatches", ["crossmatched_by"])

    # ---------------- 3. HD-30: CONFIGURABLE FORMS & ORDER SETS ----------------
    op.create_table(
        "form_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(50), nullable=False, server_default="published"),
        sa.Column("fields_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_form_definitions_code", "form_definitions", ["code"])
    op.create_index("ix_form_definitions_created_by", "form_definitions", ["created_by"])

    op.create_table(
        "form_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("form_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("form_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("form_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_form_submissions_patient_id", "form_submissions", ["patient_id"])
    op.create_index("ix_form_submissions_visit_id", "form_submissions", ["visit_id"])
    op.create_index("ix_form_submissions_form_id", "form_submissions", ["form_id"])
    op.create_index("ix_form_submissions_submitted_by", "form_submissions", ["submitted_by"])

    op.create_table(
        "clinical_order_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="general"),
        sa.Column("orders", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_clinical_order_sets_category", "clinical_order_sets", ["category"])

    # ---------------- 4. HD-31: SAFE OUTBOX DEAD LETTER QUEUE ----------------
    op.create_table(
        "outbox_dead_letter",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("original_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_outbox_dead_letter_original_event_id", "outbox_dead_letter", ["original_event_id"])
    op.create_index("ix_outbox_dead_letter_aggregate_type", "outbox_dead_letter", ["aggregate_type"])

    # ---------------- 5. HD-32: DIRECT SERVICE ENCOUNTER TYPE ----------------
    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_VISIT_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE visits ADD CONSTRAINT "{_VISIT_CONSTRAINT}" '
        f"CHECK ((visit_type)::text = ANY ((ARRAY[{_VISIT_TYPE_NEW}])::text[]))"
    )


def downgrade() -> None:
    # Check if direct_service visits exist
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM visits WHERE visit_type = 'direct_service'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} visit(s) still have visit_type='direct_service'. Reassign or "
            "cancel them before downgrading."
        )
    op.execute(f'ALTER TABLE visits DROP CONSTRAINT "{_VISIT_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE visits ADD CONSTRAINT "{_VISIT_CONSTRAINT}" '
        f"CHECK ((visit_type)::text = ANY ((ARRAY[{_VISIT_TYPE_OLD}])::text[]))"
    )

    op.drop_table("outbox_dead_letter")
    op.drop_table("clinical_order_sets")
    op.drop_table("form_submissions")
    op.drop_table("form_definitions")
    op.drop_table("blood_crossmatches")
    op.drop_table("immunization_records")
    op.drop_table("vaccine_catalogue")
