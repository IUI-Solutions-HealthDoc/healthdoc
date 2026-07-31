"""0024_patient_allergies

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-30

B3-W6-01: patient_allergies table, backing the allergy-check half of
the CDS stub (rule-based interaction flag + allergy check on
prescription save, #229).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_allergies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("allergen", sa.Text(), nullable=False),
        sa.Column("reaction", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(30), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_patient_allergies_patient_id", "patient_allergies", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_patient_allergies_patient_id", table_name="patient_allergies")
    op.drop_table("patient_allergies")
