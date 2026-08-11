"""0024_procurement

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-11

Builds: purchase_orders, purchase_order_items, stock_transfers,
        stock_transfer_items, machine_maintenance_logs
Alters: grn.purchase_order_id, adjustments.adjustment_type
        (schema.md §3, migration 0024)

Same reason as 0023: no issue was ever created for this migration, so nobody
was assigned it. 0024 sits between 0023 and Ajay's 0025, which means it is
one of three migrations holding up eleven others. Transcribed from §3, not
designed here.

Sits directly on Riya's merged 0012/0013 — suppliers, inventory_items,
stock_locations, inventory_batches, grn and adjustments all already exist.

Two things §3 is explicit about and this follows:

  * Damage write-offs get NO new table. 0024 adds
    adjustments.adjustment_type; the dual-signoff flow in 0013 already
    covers the workflow. A separate write_offs table would fork the
    approval path.
  * Each transfer leg writes stock_ledger ('transfer' out / in). That is
    service-layer behaviour, not enforced here — stock_ledger already has
    'transfer' in its transaction_type CHECK from 0012.

Models for these tables belong in app/inventory/ and are deliberately not
added here. Schema first so the chain moves.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------- purchase_orders
    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("po_number", sa.String(30), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        sa.CheckConstraint(
            "status IN ('draft','approved','sent','partially_received',"
            "'received','cancelled')",
            name="ck_purchase_orders_status",
        ),
    )
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_facility_id", "purchase_orders", ["facility_id"])

    # --------------------------------------------- purchase_order_items
    # CASCADE, unlike almost everything else in this schema: a PO line has
    # no meaning without its PO, and §3 says CASCADE explicitly. Contrast
    # stock_ledger, where RESTRICT protects the audit trail.
    op.create_table(
        "purchase_order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_order_items_quantity_positive"),
    )
    op.create_index("ix_purchase_order_items_purchase_order_id",
                    "purchase_order_items", ["purchase_order_id"])

    # grn precedes PO in migration order (0012) but follows it in workflow,
    # so the link is retrofitted here. NULL because stock can arrive without
    # a PO — donations, emergency local purchase.
    op.add_column("grn", sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True),
                                   nullable=True))
    op.create_foreign_key("fk_grn_purchase_order_id", "grn", "purchase_orders",
                          ["purchase_order_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_grn_purchase_order_id", "grn", ["purchase_order_id"])

    # -------------------------------------------------- stock_transfers
    op.create_table(
        "stock_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("from_location_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("to_location_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="requested"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('requested','in_transit','received','cancelled')",
            name="ck_stock_transfers_status",
        ),
        # A transfer to itself would write two ledger rows that cancel out
        # and leave the stock untraceable. §3 requires this.
        sa.CheckConstraint("from_location_id <> to_location_id",
                           name="ck_stock_transfers_distinct_locations"),
    )
    op.create_index("ix_stock_transfers_from_location_id", "stock_transfers",
                    ["from_location_id"])
    op.create_index("ix_stock_transfers_to_location_id", "stock_transfers",
                    ["to_location_id"])

    # --------------------------------------------- stock_transfer_items
    op.create_table(
        "stock_transfer_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("stock_transfer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_stock_transfer_items_quantity_positive"),
    )
    op.create_index("ix_stock_transfer_items_stock_transfer_id",
                    "stock_transfer_items", ["stock_transfer_id"])
    op.create_index("ix_stock_transfer_items_batch_id", "stock_transfer_items", ["batch_id"])

    # ------------------------------------------ machine_maintenance_logs
    op.create_table(
        "machine_maintenance_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("machine_id", sa.String(50), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("maintenance_type", sa.String(50), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("performed_by_vendor", sa.Text(), nullable=True),
        sa.Column("downtime_minutes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "maintenance_type IN ('preventive','breakdown','calibration','qa_check')",
            name="ck_machine_maintenance_logs_maintenance_type",
        ),
    )
    op.create_index("ix_machine_maintenance_logs_machine_id",
                    "machine_maintenance_logs", ["machine_id"])

    # Damage write-offs reuse the existing dual-signoff adjustments flow
    # rather than getting their own table — §3 is explicit about this.
    op.add_column("adjustments", sa.Column("adjustment_type", sa.String(30), nullable=True))
    op.create_check_constraint(
        "ck_adjustments_adjustment_type", "adjustments",
        "adjustment_type IS NULL OR adjustment_type IN "
        "('damage','expiry','count_error','other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_adjustments_adjustment_type", "adjustments", type_="check")
    op.drop_column("adjustments", "adjustment_type")
    op.drop_index("ix_machine_maintenance_logs_machine_id",
                  table_name="machine_maintenance_logs")
    op.drop_table("machine_maintenance_logs")
    op.drop_index("ix_stock_transfer_items_batch_id", table_name="stock_transfer_items")
    op.drop_index("ix_stock_transfer_items_stock_transfer_id",
                  table_name="stock_transfer_items")
    op.drop_table("stock_transfer_items")
    op.drop_index("ix_stock_transfers_to_location_id", table_name="stock_transfers")
    op.drop_index("ix_stock_transfers_from_location_id", table_name="stock_transfers")
    op.drop_table("stock_transfers")
    op.drop_index("ix_grn_purchase_order_id", table_name="grn")
    op.drop_constraint("fk_grn_purchase_order_id", "grn", type_="foreignkey")
    op.drop_column("grn", "purchase_order_id")
    op.drop_index("ix_purchase_order_items_purchase_order_id",
                  table_name="purchase_order_items")
    op.drop_table("purchase_order_items")
    op.drop_index("ix_purchase_orders_facility_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_supplier_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
