"""Dedicated, lease-based ABDM work queue (no clinical payloads)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abdm_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('context_notify','hip_transfer','hip_notify')", name="abdm_job_kind"
        ),
        sa.CheckConstraint("status IN ('pending','leased','done','dead')", name="abdm_job_status"),
        sa.CheckConstraint("attempts >= 0", name="abdm_job_attempts"),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)", name="abdm_job_lease_pair"
        ),
    )
    op.create_index("ix_abdm_jobs_facility_id", "abdm_jobs", ["facility_id"])
    op.create_index("ix_abdm_jobs_ready", "abdm_jobs", ["status", "available_at"])


def downgrade() -> None:
    op.drop_table("abdm_jobs")
