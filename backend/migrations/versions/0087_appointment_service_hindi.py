"""Nullable Hindi labels for appointment service catalogue.

Revision ID: 0087
Revises: 0086
Create Date: 2026-09-25

English ``name`` remains required. Hindi is optional; the UI falls back
to English when null or blank. Appointment ``service_name`` snapshots
stay English as stored at booking time.
"""
from alembic import op
import sqlalchemy as sa

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "appointment_services",
        sa.Column("name_hi", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointment_services", "name_hi")
