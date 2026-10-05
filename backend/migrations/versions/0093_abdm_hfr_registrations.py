"""Keep what HealthDoc sent HFR, so a registered facility can be edited.

Revision ID: 0093
Revises: 0092
Create Date: 2026-10-05

HFR's facility update (M4 HFR-064 to 114) re-sends basic and detailed
information under the facility's tracking id and resubmits. HFR has no call
returning the saved details, so the forms HealthDoc sent are kept here, image
content excluded, to open an edit with them. Purely additive.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abdm_hfr_registrations",
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
        sa.Column("tracking_id", sa.String(20), nullable=False),
        sa.Column("hfr_facility_id", sa.String(12), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("basic", postgresql.JSONB(), nullable=True),
        sa.Column("additional", postgresql.JSONB(), nullable=True),
        sa.Column("detailed", postgresql.JSONB(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "facility_id", "tracking_id", name="uq_abdm_hfr_registrations_tracking"
        ),
    )
    op.create_index(
        "ix_abdm_hfr_registrations_created_by", "abdm_hfr_registrations", ["created_by"]
    )
    op.create_index(
        "ix_abdm_hfr_registrations_updated_by", "abdm_hfr_registrations", ["updated_by"]
    )


def downgrade() -> None:
    op.drop_index("ix_abdm_hfr_registrations_updated_by", table_name="abdm_hfr_registrations")
    op.drop_index("ix_abdm_hfr_registrations_created_by", table_name="abdm_hfr_registrations")
    op.drop_table("abdm_hfr_registrations")
