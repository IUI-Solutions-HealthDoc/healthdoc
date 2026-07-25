"""Migration 0019 — B3-W3-02. order_number_counters: race-safe daily sequence for order numbers.

Replaces the COUNT(*)-based generator in app.orders.order_number, which had
a race condition under concurrent order creation (flagged in that module's
own comments). One row per day, locked with SELECT ... FOR UPDATE.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_number_counters",
        sa.Column("counter_date", sa.Date(), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("order_number_counters")
