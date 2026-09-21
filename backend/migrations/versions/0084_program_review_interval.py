"""Optional program review interval. No invented 30-day default.

Revision ID: 0084
Revises: 0083
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "care_programs",
        sa.Column("review_interval_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("care_programs", "review_interval_days")
