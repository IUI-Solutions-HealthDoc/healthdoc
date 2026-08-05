"""Migration 0028 — user_account_requests (B1-W3-01).

Maker-checker table for self-service account requests. A requester submits a
request; a different user (approver) must approve or reject it. The DB CHECK
enforces that requester ≠ approver — the service layer alone is not enough.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_account_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("mobile", sa.String(20), nullable=True),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT",
                                name="fk_user_account_requests_facility_id"),
                  nullable=False),
        sa.Column("requested_roles", sa.String(500), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("requester_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_user_account_requests_requester_id"),
                  nullable=False),
        sa.Column("approver_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_user_account_requests_approver_id"),
                  nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_user_account_requests_status",
        ),
        sa.CheckConstraint(
            "approver_id IS NULL OR approver_id != requester_id",
            name="ck_user_account_requests_requester_ne_approver",
        ),
    )
    op.create_index("ix_user_account_requests_facility_id",
                     "user_account_requests", ["facility_id"])
    op.create_index("ix_user_account_requests_requester_id",
                     "user_account_requests", ["requester_id"])
    op.create_index("ix_user_account_requests_approver_id",
                     "user_account_requests", ["approver_id"])
    op.create_index("ix_user_account_requests_status",
                     "user_account_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_user_account_requests_status", table_name="user_account_requests")
    op.drop_index("ix_user_account_requests_approver_id", table_name="user_account_requests")
    op.drop_index("ix_user_account_requests_requester_id", table_name="user_account_requests")
    op.drop_index("ix_user_account_requests_facility_id", table_name="user_account_requests")
    op.drop_table("user_account_requests")
