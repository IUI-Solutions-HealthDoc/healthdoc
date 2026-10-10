"""Facilities choose whether their free beds and blood stock are public.

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-10

The public availability page (/availability, no login) lists only facilities
that have opted in. Off by default: publishing a hospital's bed and blood
counts is a decision for its owner, not a side effect of an upgrade.
"""

import sqlalchemy as sa
from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facilities",
        sa.Column("publish_availability", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("facilities", "publish_availability")
