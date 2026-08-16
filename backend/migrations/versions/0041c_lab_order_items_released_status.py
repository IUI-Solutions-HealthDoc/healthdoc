"""0041c_lab_order_items_released_status

Revision ID: 0041c
Revises: 0041b
Create Date: 2026-08-14

Fifth schema gap found via #243 — same bug class as radiology's own
documented fix in 0020c, just never applied to lab.

app/common/enums.py's RadiologyOrderStatus docstring explains this exact
issue already happened once and was fixed for radiology:
  "0011 originally constrained radiology_order_items.status to
  OrderStatus, which no code path could satisfy -- the router has
  always set scheduled, scanned, reporting and released. Corrected in
  0020c."

lab_order_items never got the equivalent fix. app/pathology/router.py's
verify_result sets item.status = "released" (mirroring
app/radiology/router.py's identical line), but
ck_lab_order_items_ck_lab_order_items_status only allows
placed|accepted|in_progress|completed|cancelled -- 'released' isn't in
it, so every lab result verification fails with a CheckViolationError.

Uses raw SQL (op.execute) rather than op.create_check_constraint /
op.drop_constraint deliberately: Alembic's helpers auto-prefix the given
name with ck_<table>_, and this constraint's real name
(ck_lab_order_items_ck_lab_order_items_status) already contains that
prefix once -- passing it through the helper would double-prefix it to
ck_lab_order_items_ck_lab_order_items_ck_lab_order_items_status, which
doesn't exist and makes drop_constraint fail. Raw SQL uses the exact
existing name with no transformation.
"""
from alembic import op

revision = "0041c"
down_revision = "0041b"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_lab_order_items_ck_lab_order_items_status"
OLD_VALUES = "'placed', 'accepted', 'in_progress', 'completed', 'cancelled'"
NEW_VALUES = "'placed', 'accepted', 'in_progress', 'completed', 'cancelled', 'released'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE lab_order_items DROP CONSTRAINT {CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE lab_order_items ADD CONSTRAINT {CONSTRAINT_NAME} "
        f"CHECK (status IN ({NEW_VALUES}))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE lab_order_items DROP CONSTRAINT {CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE lab_order_items ADD CONSTRAINT {CONSTRAINT_NAME} "
        f"CHECK (status IN ({OLD_VALUES}))"
    )