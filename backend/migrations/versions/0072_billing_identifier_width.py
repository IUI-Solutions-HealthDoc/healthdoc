"""Preserve complete billing identifiers for permitted 20-character facility codes."""

import sqlalchemy as sa
from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

FIELDS = (
    ("invoices", "invoice_number"),
    ("payments", "receipt_number"),
    ("refunds", "refund_number"),
)


def upgrade() -> None:
    for table, column in FIELDS:
        op.alter_column(
            table, column,
            existing_type=sa.String(30),  # pr-check: ignore — existing identifier width, widened below
            type_=sa.String(50),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Check every table before narrowing any. Never truncate issued numbers.
    for table, column in FIELDS:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE length({column}) > 30) "
            "THEN RAISE EXCEPTION 'Long billing identifiers exist; reviewed recovery required'; "
            "END IF; END $$"
        )
    for table, column in FIELDS:
        op.alter_column(
            table, column, existing_type=sa.String(50), type_=sa.String(30),
            existing_nullable=False,
        )
