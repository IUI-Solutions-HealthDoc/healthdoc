"""Persist immutable recipient-encrypted HIP pages and per-page delivery progress."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abdm_hip_transfer_pages",
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
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("abdm_hip_hi_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "context_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("abdm_care_contexts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("document_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("request_id", "page_number", name="uq_abdm_hip_page_number"),
        sa.UniqueConstraint("request_id", "context_id", name="uq_abdm_hip_page_context"),
        sa.CheckConstraint("page_number >= 0", name="abdm_hip_page_number"),
    )
    op.create_index(
        "ix_abdm_hip_transfer_pages_facility_id", "abdm_hip_transfer_pages", ["facility_id"]
    )
    op.create_index(
        "ix_abdm_hip_transfer_pages_request_id", "abdm_hip_transfer_pages", ["request_id"]
    )
    op.create_index(
        "ix_abdm_hip_transfer_pages_context_id", "abdm_hip_transfer_pages", ["context_id"]
    )


def downgrade() -> None:
    op.drop_table("abdm_hip_transfer_pages")
