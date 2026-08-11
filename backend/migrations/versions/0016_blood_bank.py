"""0016_blood_bank

Revision ID: 0016
Revises: 0015
Schema only - no API/business logic in this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import BloodGroup, ScreeningStatus, BloodUnitStatus

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # blood_donors
    op.create_table(
        "blood_donors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("sex", sa.String(50), nullable=True),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("age_years", sa.Integer(), nullable=True),
        sa.Column("blood_group", sa.String(50), nullable=False),
        sa.Column("mobile", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=True),
        sa.Column("hemoglobin_g_dl", sa.Numeric(4, 1), nullable=True),
        sa.Column("last_donation_date", sa.Date(), nullable=True),
        sa.Column("next_eligible_date", sa.Date(), nullable=True),
        sa.Column(
            "is_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_blood_donors_blood_group", "blood_donors", BloodGroup.sql_check("blood_group"),
    )
    op.create_index("ix_blood_donors_patient_id", "blood_donors", ["patient_id"])
    op.create_index("ix_blood_donors_created_by", "blood_donors", ["created_by"])

    # blood_units 
    op.create_table(
        "blood_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("donor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("blood_donors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bag_number", sa.String(30), nullable=False, unique=True),
        sa.Column("blood_group", sa.String(50), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("screening_status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'available'")),
        sa.Column("issued_to_patient_id", postgresql.UUID(as_uuid=True),
         sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_blood_units_volume_ml", "blood_units", "volume_ml > 0",
    )
    op.create_check_constraint(
        "ck_blood_units_screening_status", "blood_units", ScreeningStatus.sql_check("screening_status"),
    )
    op.create_check_constraint(
        "ck_blood_units_status", "blood_units", BloodUnitStatus.sql_check("status"),
    )
    op.create_check_constraint(
        "ck_blood_units_blood_group", "blood_units", BloodGroup.sql_check("blood_group"),
    )
    op.create_index("ix_blood_units_donor_id", "blood_units", ["donor_id"])
    op.create_index("ix_blood_units_issued_to_patient_id", "blood_units", ["issued_to_patient_id"])


def downgrade() -> None:
    op.drop_table("blood_units")
    op.drop_table("blood_donors")
