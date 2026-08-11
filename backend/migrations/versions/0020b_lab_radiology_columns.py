"""0020b_lab_radiology_columns

Revision ID: 0020b
Revises: 0020a
Create Date: 2026-08-10

Adds four columns the pathology and radiology ORM models declare but no
migration ever created:

    lab_order_items.barcode            sample barcode (#166)
    lab_order_items.collected_at       when the sample was taken (#166)
    lab_results.amendment_reason       why a corrected result was issued
    radiology_order_items.scan_completed_at   TAT baseline

The models have carried these since the modules were written; 0010 and 0011
did not. Nothing caught it because the module was never importable — the
routers had a syntax error and ten malformed dependencies — so the tests
that would have touched these columns never ran. The first green CI run
against a real database failed with
"column lab_order_items.barcode does not exist".

Worth naming the checker gap: schema_drift_check compares §3 against the
migrations, and pr_check reads source, but nothing compares the ORM against
the migrations. All four of these are absent from §3 as well, so no existing
check could have seen them. §3 entries added alongside this migration.

All four are nullable with no default — they are set later in the workflow
(a sample is collected after it is ordered; an amendment reason exists only
on an amendment), so no backfill is needed.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020b"
down_revision = "0020a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # UNIQUE: a barcode identifies one physical sample. Two rows sharing one
    # is a mislabelled tube, which is the error this column exists to make
    # impossible rather than merely unlikely. Nullable because the barcode is
    # assigned at collection, not at ordering.
    op.add_column("lab_order_items", sa.Column("barcode", sa.String(50), nullable=True))
    op.create_unique_constraint(
        "uq_lab_order_items_barcode", "lab_order_items", ["barcode"]
    )
    op.add_column(
        "lab_order_items",
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("lab_results", sa.Column("amendment_reason", sa.Text(), nullable=True))

    op.add_column(
        "radiology_order_items",
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("radiology_order_items", "scan_completed_at")
    op.drop_column("lab_results", "amendment_reason")
    op.drop_column("lab_order_items", "collected_at")
    op.drop_constraint("uq_lab_order_items_barcode", "lab_order_items", type_="unique")
    op.drop_column("lab_order_items", "barcode")
