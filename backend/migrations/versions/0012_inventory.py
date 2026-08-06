import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contact_info", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_suppliers_facility_id", "suppliers", ["facility_id"])

    op.create_table(
        "inventory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("generic_name", sa.Text()),
        sa.Column("strength", sa.String(50)),
        sa.Column("form", sa.String(50)),
        sa.Column("item_type", sa.String(50)),
        sa.Column("is_controlled_drug", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manufacturer", sa.Text()),
        sa.Column("owning_department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("reorder_level", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "form IN ('tablet','capsule','injection','syrup','ointment','fluid',"
            "'reagent','consumable','film','implant','blood_component')",
            name="ck_inventory_items_form",
        ),
        sa.CheckConstraint(
            "item_type IN ('medicine','reagent','consumable','film','implant',"
            "'blood_component')",
            name="ck_inventory_items_item_type",
        ),
    )
    op.create_index("ix_inventory_items_owning_department_id", "inventory_items", ["owning_department_id"])

    op.create_table(
        "stock_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location_type", sa.String(50)),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "location_type IN ('central','pharmacy','lab','radiology','ward','emergency','ot')",
            name="ck_stock_locations_location_type",
        ),
    )
    op.create_index("ix_stock_locations_department_id", "stock_locations", ["department_id"])
    op.create_index("ix_stock_locations_facility_id", "stock_locations", ["facility_id"])

    op.create_table(
        "inventory_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("batch_number", sa.String(50), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("purchase_rate", sa.Numeric(12, 2)),
        sa.Column("issue_rate_mrp", sa.Numeric(12, 2)),
        sa.Column("stock_location_id", UUID(as_uuid=True),
                  sa.ForeignKey("stock_locations.id"), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_batches_quantity"),
        sa.UniqueConstraint(
            "item_id", "batch_number", "stock_location_id",
            name="uq_inventory_batches_item_id_batch_number_stock_location_id",
        ),
    )
    op.create_index("ix_inventory_batches_stock_location_id", "inventory_batches", ["stock_location_id"])
    op.execute("""
        CREATE INDEX ix_inventory_batches_fefo
        ON inventory_batches (item_id, expiry_date ASC)
        WHERE quantity > 0
    """)

    op.create_table(
        "stock_ledger",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_batches.id"), nullable=True),
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("reference_type", sa.String(50)),
        sa.Column("reference_id", UUID(as_uuid=True)),
        sa.Column("performed_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "transaction_type IN ('purchase','issue','return','transfer','consumption','adjustment','write_off')",
            name="ck_stock_ledger_transaction_type",
        ),
        sa.CheckConstraint("quantity <> 0", name="ck_stock_ledger_quantity_nonzero"),
        sa.CheckConstraint(
            "(transaction_type IN ('purchase','return') AND quantity > 0) OR "
            "(transaction_type IN ('issue','consumption','write_off') AND quantity < 0) OR "
            "(transaction_type IN ('adjustment','transfer'))",
            name="ck_stock_ledger_quantity_sign_matches_type",
        ),
    )
    op.create_index("ix_stock_ledger_item_id", "stock_ledger", ["item_id"])
    op.create_index("ix_stock_ledger_batch_id", "stock_ledger", ["batch_id"])
    op.create_index("ix_stock_ledger_performed_by", "stock_ledger", ["performed_by"])

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_stock_ledger_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'stock_ledger is append-only: % not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_stock_ledger_block_update
        BEFORE UPDATE OR DELETE ON stock_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_stock_ledger_mutation()
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION apply_stock_ledger_to_batch()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.batch_id IS NOT NULL THEN
                UPDATE inventory_batches
                SET quantity = quantity + NEW.quantity,
                    row_version = row_version + 1,
                    updated_at = NOW()
                WHERE id = NEW.batch_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_stock_ledger_apply_to_batch
        AFTER INSERT ON stock_ledger
        FOR EACH ROW EXECUTE FUNCTION apply_stock_ledger_to_batch()
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION guard_inventory_batches_quantity()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.quantity IS DISTINCT FROM OLD.quantity THEN
                IF pg_trigger_depth() < 2 THEN
                    RAISE EXCEPTION
                        'inventory_batches.quantity may only change via a stock_ledger insert';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_inventory_batches_guard_quantity
        BEFORE UPDATE OF quantity ON inventory_batches
        FOR EACH ROW EXECUTE FUNCTION guard_inventory_batches_quantity()
    """)

    op.execute("""
        ALTER TABLE prescription_items
        ADD CONSTRAINT fk_prescription_items_medicine_item_id
        FOREIGN KEY (medicine_item_id) REFERENCES inventory_items(id)
    """)
    op.execute("CREATE INDEX ix_prescription_items_medicine_item_id ON prescription_items (medicine_item_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE prescription_items DROP CONSTRAINT IF EXISTS fk_prescription_items_medicine_item_id")
    op.execute("DROP INDEX IF EXISTS ix_prescription_items_medicine_item_id")

    op.execute("DROP TRIGGER IF EXISTS trg_inventory_batches_guard_quantity ON inventory_batches")
    op.execute("DROP FUNCTION IF EXISTS guard_inventory_batches_quantity()")

    op.execute("DROP TRIGGER IF EXISTS trg_stock_ledger_apply_to_batch ON stock_ledger")
    op.execute("DROP FUNCTION IF EXISTS apply_stock_ledger_to_batch()")

    op.execute("DROP TRIGGER IF EXISTS trg_stock_ledger_block_update ON stock_ledger")
    op.execute("DROP FUNCTION IF EXISTS prevent_stock_ledger_mutation()")

    op.drop_table("stock_ledger")
    op.execute("DROP INDEX IF EXISTS ix_inventory_batches_fefo")
    op.drop_table("inventory_batches")
    op.drop_table("stock_locations")
    op.drop_table("inventory_items")
    op.drop_table("suppliers")
