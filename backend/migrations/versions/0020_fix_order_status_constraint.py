"""Migration 0020 — B3-W3-02 bugfix. orders.status CHECK constraint was
missing 'accepted', which is a valid OrderStatus enum value. Migration
0008 drifted from app.common.enums.OrderStatus at some point; this
corrects the constraint to match the current enum.

Uses raw SQL (op.execute) rather than op.drop_constraint/create_check_constraint
because those auto-apply Alembic's naming convention, which would have
double-prefixed the already-prefixed legacy constraint name.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders DROP CONSTRAINT ck_orders_ck_orders_status")
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_status "
        "CHECK (status IN ('placed', 'accepted', 'in_progress', 'completed', 'cancelled'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP CONSTRAINT ck_orders_status")
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_ck_orders_status "
        "CHECK (status IN ('placed', 'in_progress', 'completed', 'cancelled'))"
    )
