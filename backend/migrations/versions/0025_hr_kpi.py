"""Migration 0025 — HR / KPI tables (B1).

staff_certifications, staff_training_records, kpi_snapshots.
Nothing currently depends on these — they're the last B1 migration.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # staff_certifications — tracks professional certifications (medical license, etc.)
    op.create_table(
        "staff_certifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE",
                                name="fk_staff_certifications_user_id"),
                  nullable=False),
        sa.Column("certification_name", sa.Text(), nullable=False),
        sa.Column("issuing_body", sa.Text(), nullable=True),
        sa.Column("certificate_number", sa.String(100), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_staff_certifications_user_id",
                     "staff_certifications", ["user_id"])

    # staff_training_records — training and continuing education
    op.create_table(
        "staff_training_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE",
                                name="fk_staff_training_records_user_id"),
                  nullable=False),
        sa.Column("training_type", sa.String(50), nullable=False),
        sa.Column("training_name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("score", sa.String(50), nullable=True),
        sa.Column("certificate_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "training_type IN ('induction','clinical','digital_health','safety','other')",
            name="ck_staff_training_records_training_type",
        ),
    )
    op.create_index("ix_staff_training_records_user_id",
                     "staff_training_records", ["user_id"])

    # kpi_snapshots — periodic performance snapshots per user
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="CASCADE",
                                name="fk_kpi_snapshots_facility_id"),
                  nullable=False),
        sa.Column("kpi_code", sa.String(50), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 4), nullable=False),
        sa.Column("numerator", sa.Numeric(), nullable=True),
        sa.Column("denominator", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("facility_id", "kpi_code", "period_start", "period_end",
                            name="uq_kpi_snapshots_facility_code_period"),
    )


def downgrade() -> None:
    op.drop_table("kpi_snapshots")
    op.drop_index("ix_staff_training_records_user_id", table_name="staff_training_records")
    op.drop_table("staff_training_records")
    op.drop_index("ix_staff_certifications_user_id", table_name="staff_certifications")
    op.drop_table("staff_certifications")
