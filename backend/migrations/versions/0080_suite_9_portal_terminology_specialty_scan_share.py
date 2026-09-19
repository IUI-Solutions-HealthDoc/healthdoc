"""Suite 9: Specialty encounters and ABDM M1 scan-and-share reception tickets (HD-33 to HD-36).

Revision ID: 0080
Revises: 0079
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- 1. HD-34: SPECIALTY ENCOUNTERS ----------------
    op.create_table(
        "specialty_encounters",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("specialty_type", sa.String(50), nullable=False),
        sa.Column("clinical_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_specialty_encounters_encounter_id", "specialty_encounters", ["encounter_id"])
    op.create_index("ix_specialty_encounters_patient_id", "specialty_encounters", ["patient_id"])
    op.create_index("ix_specialty_encounters_created_by", "specialty_encounters", ["created_by"])
    op.create_index("ix_specialty_encounters_specialty_type", "specialty_encounters", ["specialty_type"])

    # ---------------- 2. HD-36: ABDM M1 SCAN-AND-SHARE TICKETS ----------------
    op.create_table(
        "scan_share_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_number", sa.String(30), nullable=False),
        sa.Column("abha_address", sa.String(100), nullable=False),
        sa.Column("profile_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'active'")),
        sa.Column("counter", sa.String(50), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_scan_share_tickets_facility_id", "scan_share_tickets", ["facility_id"])
    op.create_index("ix_scan_share_tickets_patient_id", "scan_share_tickets", ["patient_id"])
    op.create_index("ix_scan_share_tickets_token_number", "scan_share_tickets", ["token_number"])
    op.create_index("ix_scan_share_tickets_abha_address", "scan_share_tickets", ["abha_address"])
    op.create_index("ix_scan_share_tickets_status", "scan_share_tickets", ["status"])


def downgrade() -> None:
    op.drop_index("ix_scan_share_tickets_status", table_name="scan_share_tickets")
    op.drop_index("ix_scan_share_tickets_abha_address", table_name="scan_share_tickets")
    op.drop_index("ix_scan_share_tickets_token_number", table_name="scan_share_tickets")
    op.drop_index("ix_scan_share_tickets_patient_id", table_name="scan_share_tickets")
    op.drop_index("ix_scan_share_tickets_facility_id", table_name="scan_share_tickets")
    op.drop_table("scan_share_tickets")

    op.drop_index("ix_specialty_encounters_specialty_type", table_name="specialty_encounters")
    op.drop_index("ix_specialty_encounters_created_by", table_name="specialty_encounters")
    op.drop_index("ix_specialty_encounters_patient_id", table_name="specialty_encounters")
    op.drop_index("ix_specialty_encounters_encounter_id", table_name="specialty_encounters")
    op.drop_table("specialty_encounters")
