"""0020c_radiology_status_check

Revision ID: 0020c
Revises: 0020b
Create Date: 2026-08-10

Replaces radiology_order_items' status CHECK.

0011 constrained the column to OrderStatus — placed | accepted | in_progress
| completed | cancelled. The radiology router has never used those values: it
drives placed -> scheduled -> scanned -> reporting -> released, and its tests
assert that workflow. So every state transition after 'placed' violated the
constraint, and PUT .../scan-complete could not have worked in production.

Nothing caught it because app/radiology/router.py did not parse — it had a
shell command pasted into it at line 254 — so the module was never
importable and its tests never ran.

The workflow, not the constraint, is what's right here. A modality worklist
exists to separate "images taken, report owed" from "not yet scanned", and
OrderStatus cannot express that: both would be in_progress. See
RadiologyOrderStatus in app/common/enums.py.

lab_order_items keeps OrderStatus. Lab's router only ever sets placed and
in_progress, both of which are valid there, so it has no equivalent gap.
"""
from alembic import op

from app.common.enums import RadiologyOrderStatus

revision = "0020c"
down_revision = "0020b"
branch_labels = None
depends_on = None

_OLD_ORDER_STATUS = (
    "status IN ('placed', 'accepted', 'in_progress', 'completed', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_radiology_order_items_status", "radiology_order_items", type_="check"
    )
    op.create_check_constraint(
        "ck_radiology_order_items_status",
        "radiology_order_items",
        RadiologyOrderStatus.sql_check("status"),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_radiology_order_items_status", "radiology_order_items", type_="check"
    )
    op.create_check_constraint(
        "ck_radiology_order_items_status", "radiology_order_items", _OLD_ORDER_STATUS
    )
