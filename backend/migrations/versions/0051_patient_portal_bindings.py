"""0051 patient portal bindings — verified self-identity boundary.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_portal_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verification_method", sa.String(30), nullable=False),
        sa.Column("verification_reference", sa.Text(), nullable=False),
        sa.Column("verified_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "verification_method IN ('abha_otp','in_person_document')",
            name="verification_method",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR (revoked_by IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_complete",
        ),
    )
    op.create_index(
        "uq_patient_portal_bindings_active_user", "patient_portal_bindings", ["user_id"],
        unique=True, postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_patient_portal_bindings_active_patient", "patient_portal_bindings", ["patient_id"],
        unique=True, postgresql_where=sa.text("revoked_at IS NULL"),
    )
    for column in ("user_id", "patient_id", "facility_id", "verified_by", "revoked_by"):
        op.create_index(
            f"ix_patient_portal_bindings_{column}", "patient_portal_bindings", [column]
        )


def downgrade() -> None:
    op.drop_table("patient_portal_bindings")
