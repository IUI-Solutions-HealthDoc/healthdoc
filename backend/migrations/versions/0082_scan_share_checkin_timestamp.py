"""Persist reception check-in time without inventing times for historical tickets.

Revision ID: 0082
Revises: 0081
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_share_tickets", sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_share_tickets", "checked_in_at")
