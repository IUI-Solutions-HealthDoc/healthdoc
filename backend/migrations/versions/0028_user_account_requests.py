"""Migration 0028 — maker-checker user account requests."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_account_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_for_full_name", sa.Text(), nullable=False),
        sa.Column("requested_username", sa.String(100), nullable=False),
        sa.Column("requested_roles", ARRAY(sa.Text()), nullable=False),
        sa.Column("designation", sa.String(100)),
        sa.Column("employee_id", sa.String(30)),
        sa.Column("registration_number", sa.String(50)),
        sa.Column("qualification", sa.String(100)),
        sa.Column("email", sa.String(255)),
        sa.Column("mobile", sa.String(20)),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("decided_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','approved','rejected')",
                           name="ck_user_account_requests_status"),
        sa.CheckConstraint("decided_by IS NULL OR decided_by != requested_by",
                           name="ck_user_account_requests_requester_ne_approver"),
    )
    op.create_index("ix_user_account_requests_facility_id_status",
                    "user_account_requests", ["facility_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_user_account_requests_facility_id_status",
                  table_name="user_account_requests")
    op.drop_table("user_account_requests")
