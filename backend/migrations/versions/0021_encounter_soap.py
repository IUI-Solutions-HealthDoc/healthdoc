"""encounter SOAP fields + note_status/row_version + facility_id (encounters, diagnoses)

Revision ID: 0021
Revises: 0020c
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("encounters", sa.Column("subjective", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("objective", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("assessment", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("plan", sa.Text(), nullable=True))
    op.add_column("encounters", sa.Column("note_status", sa.String(50), nullable=False, server_default="pending"))
    op.add_column("encounters", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("note_status", "encounters", "note_status IN ('pending', 'stored', 'failed')")

    # facility_id denormalized on both tables -- required by audit auto-logging
    # (__audit_facility_id_field__ must name a real column, audit_logs.facility_id NOT NULL)
    op.add_column("encounters", sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE encounters SET facility_id = visits.facility_id FROM visits WHERE visits.id = encounters.visit_id")
    op.alter_column("encounters", "facility_id", nullable=False)
    op.create_foreign_key("fk_encounters_facility_id", "encounters", "facilities", ["facility_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_encounters_facility_id", "encounters", ["facility_id"])

    op.add_column("diagnoses", sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE diagnoses SET facility_id = encounters.facility_id FROM encounters WHERE encounters.id = diagnoses.encounter_id")
    op.alter_column("diagnoses", "facility_id", nullable=False)
    op.create_foreign_key("fk_diagnoses_facility_id", "diagnoses", "facilities", ["facility_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_diagnoses_facility_id", "diagnoses", ["facility_id"])


def downgrade() -> None:
    op.drop_index("ix_diagnoses_facility_id", table_name="diagnoses")
    op.drop_constraint("fk_diagnoses_facility_id", "diagnoses", type_="foreignkey")
    op.drop_column("diagnoses", "facility_id")
    op.drop_index("ix_encounters_facility_id", table_name="encounters")
    op.drop_constraint("fk_encounters_facility_id", "encounters", type_="foreignkey")
    op.drop_column("encounters", "facility_id")
    op.drop_constraint("note_status", "encounters", type_="check")
    op.drop_column("encounters", "row_version")
    op.drop_column("encounters", "note_status")
    op.drop_column("encounters", "plan")
    op.drop_column("encounters", "assessment")
    op.drop_column("encounters", "objective")
    op.drop_column("encounters", "subjective")
