"""Control room drill-down: what lies behind a facility's counts.

Revision ID: 0098
Revises: 0097
Create Date: 2026-10-10

Each capture also keeps the detail an officer needs to act on a red: beds by
ward, the medicines below reorder level and the batches about to expire. Lists
are bounded at capture time, and contain no patient data, so the drill-down
reads the capture like the board does and never queries clinical tables.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "facility_pulse",
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("facility_pulse", "detail")
