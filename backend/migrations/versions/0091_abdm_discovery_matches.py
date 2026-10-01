"""Durable record of a PHR discovery matched by mobile and demographics.

Revision ID: 0091
Revises: 0090
Create Date: 2026-10-01

A patient who registered with a mobile and no ABHA address is discovered by
mobile, name, gender and birth year (M2 USER_INIT_LINK_603). The link-init
that follows names the discovery transaction and the user's ABHA address, but
no chart holds that address yet, and the reply snapshot carrying the match is
erased once delivered. This table keeps the match (transaction, address,
chart, care contexts) until the link-init quotes it or it expires.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abdm_discovery_matches",
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
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.String(120), nullable=False),
        sa.Column("abha_address", sa.String(120), nullable=False),
        sa.Column("abha_number", sa.String(17), nullable=True),
        sa.Column("care_context_references", postgresql.JSONB(), nullable=False),
        sa.Column("matched_by", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "facility_id", "transaction_id", name="uq_abdm_discovery_matches_txn"
        ),
    )
    op.create_index(
        "ix_abdm_discovery_matches_patient_id", "abdm_discovery_matches", ["patient_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_abdm_discovery_matches_patient_id", table_name="abdm_discovery_matches")
    op.drop_table("abdm_discovery_matches")
