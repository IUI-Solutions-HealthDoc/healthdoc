"""0012 - inventory (B6-W1-01)

Tables: suppliers, inventory_items, stock_locations, inventory_batches,
stock_ledger. Also adds the deferred FK prescription_items.medicine_item_id
-> inventory_items.id.

Built against HealthDoc Master Database Schema v3.4.1, section 3.
Enum-backed columns use varchar(50) per the v3.4.1 blanket-rule override
(was varchar(30) in v2.2 - widened because tight widths truncate silently
as the vocabulary grows).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-22
"""
from alembic import op

revision = "0012"
down_revision = "0011"  # confirm this matches the actual head in your synced repo
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # suppliers
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE suppliers (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            contact_info TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ---------------------------------------------------------------
    # inventory_items
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE inventory_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            generic_name TEXT,
            strength VARCHAR(50),
            form VARCHAR(50)
                CONSTRAINT ck_inventory_items_form
                CHECK (form IN ('tablet','capsule','injection','syrup','ointment','fluid','reagent','consumable','film','implant','blood_component')),
            item_type VARCHAR(50)
                CONSTRAINT ck_inventory_items_item_type
                CHECK (item_type IN ('medicine','reagent','consumable','film','implant','blood_component')),
            is_controlled_drug BOOLEAN NOT NULL DEFAULT FALSE,
            manufacturer TEXT,
            owning_department_id UUID NULL REFERENCES departments(id),
            reorder_level NUMERIC(12,2) NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_inventory_items_owning_department_id ON inventory_items (owning_department_id)")

    # ---------------------------------------------------------------
    # stock_locations
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE stock_locations (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            location_type VARCHAR(50)
                CONSTRAINT ck_stock_locations_location_type
                CHECK (location_type IN ('central','pharmacy','lab','radiology','ward','emergency','ot')),
            department_id UUID NULL REFERENCES departments(id),
            facility_id UUID NOT NULL REFERENCES facilities(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_stock_locations_department_id ON stock_locations (department_id)")
    op.execute("CREATE INDEX ix_stock_locations_facility_id ON stock_locations (facility_id)")

    # ---------------------------------------------------------------
    # inventory_batches
    # No CHECK against CURRENT_DATE: not immutable, blocks legitimate
    # historical rows. Expiry filtering happens in FEFO query logic.
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE inventory_batches (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            batch_number VARCHAR(50) NOT NULL,
            expiry_date DATE NOT NULL,
            quantity NUMERIC(12,2) NOT NULL CHECK (quantity >= 0),
            purchase_rate NUMERIC(12,2),
            issue_rate_mrp NUMERIC(12,2),
            stock_location_id UUID NOT NULL REFERENCES stock_locations(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (item_id, batch_number, stock_location_id)
        )
    """)
    op.execute("CREATE INDEX ix_inventory_batches_stock_location_id ON inventory_batches (stock_location_id)")
    op.execute("""
        CREATE INDEX ix_inventory_batches_fefo
        ON inventory_batches (item_id, expiry_date ASC)
        WHERE quantity > 0
    """)

    # ---------------------------------------------------------------
    # stock_ledger (append-only)
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE stock_ledger (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            batch_id UUID NULL REFERENCES inventory_batches(id),
            transaction_type VARCHAR(50) NOT NULL
                CONSTRAINT ck_stock_ledger_transaction_type
                CHECK (transaction_type IN ('purchase','issue','return','transfer','consumption','adjustment','write_off')),
            quantity NUMERIC(12,2) NOT NULL CHECK (quantity <> 0),
            reference_type VARCHAR(30),
            reference_id UUID,
            performed_by UUID NOT NULL REFERENCES users(id),
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_stock_ledger_item_id ON stock_ledger (item_id)")
    op.execute("CREATE INDEX ix_stock_ledger_batch_id ON stock_ledger (batch_id)")
    op.execute("CREATE INDEX ix_stock_ledger_performed_by ON stock_ledger (performed_by)")

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

    # ---------------------------------------------------------------
    # Deferred FK: prescription_items.medicine_item_id -> inventory_items.id
    # ---------------------------------------------------------------
    op.execute("""
        ALTER TABLE prescription_items
        ADD CONSTRAINT fk_prescription_items_medicine_item_id
        FOREIGN KEY (medicine_item_id) REFERENCES inventory_items(id)
    """)
    op.execute("CREATE INDEX ix_prescription_items_medicine_item_id ON prescription_items (medicine_item_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE prescription_items DROP CONSTRAINT IF EXISTS fk_prescription_items_medicine_item_id")
    op.execute("DROP INDEX IF EXISTS ix_prescription_items_medicine_item_id")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_ledger_block_update ON stock_ledger")
    op.execute("DROP FUNCTION IF EXISTS prevent_stock_ledger_mutation()")
    op.execute("DROP TABLE IF EXISTS stock_ledger")
    op.execute("DROP INDEX IF EXISTS ix_inventory_batches_fefo")
    op.execute("DROP TABLE IF EXISTS inventory_batches")
    op.execute("DROP TABLE IF EXISTS stock_locations")
    op.execute("DROP TABLE IF EXISTS inventory_items")
    op.execute("DROP TABLE IF EXISTS suppliers")
