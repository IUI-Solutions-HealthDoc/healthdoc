"""Distinguish evidence-derived timing KPIs from legacy placeholder values.

Revision ID: 0081
Revises: 0080
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill: old rows were not measured by the new producer. Retain them
    # for review, but never label them as verified by setting a default here.
    op.add_column("kpi_snapshots", sa.Column("calculation_version", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("kpi_snapshots", "calculation_version")
