"""Permit a one-day tariff in the existing inclusive effective-date interval."""
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

# 0033 passed a prefixed name through the naming convention. Preserve the
# actual database name; op.f prevents it being prefixed for a third time.
CONSTRAINT = "ck_charge_master_ck_charge_master_effective_range"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "charge_master", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "charge_master",
        "effective_to IS NULL OR effective_to >= effective_from",
    )


def downgrade() -> None:
    # Do not delete or extend a valid one-day price just to roll the code back.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM charge_master WHERE effective_to = effective_from) "
        "THEN RAISE EXCEPTION 'One-day tariffs exist; reviewed rollback required'; END IF; END $$"
    )
    op.drop_constraint(op.f(CONSTRAINT), "charge_master", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "charge_master",
        "effective_to IS NULL OR effective_to > effective_from",
    )
