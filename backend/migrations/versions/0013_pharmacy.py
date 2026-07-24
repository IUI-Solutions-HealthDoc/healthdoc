"""0013 - pharmacy (B6-W1-01)

Tables: pharmacy_dispenses, pharmacy_dispense_items, grn, grn_items,
indents, indent_items, adjustments, facility_settings.

audit_logs is NOT created here - owned by B7/Vani (migration 0003).
Mutations on these tables write through the shared audit middleware.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-22
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # pharmacy_dispenses (version + is_current pattern, no previous_version_id)
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE pharmacy_dispenses (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            prescription_id UUID NOT NULL REFERENCES prescriptions(id),
            visit_id UUID NULL REFERENCES visits(id),
            status VARCHAR(50) NOT NULL
                CONSTRAINT ck_pharmacy_dispenses_status
                CHECK (status IN ('received','in_progress','partially_dispensed','dispensed','out_of_stock','substitute_suggested','doctor_approval_required','returned','cancelled')),
            dispensed_by UUID NOT NULL REFERENCES users(id),
            version INT NOT NULL,
            is_current BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (prescription_id, version)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_pharmacy_dispenses_current
        ON pharmacy_dispenses (prescription_id)
        WHERE is_current
    """)
    op.execute("CREATE INDEX ix_pharmacy_dispenses_visit_id ON pharmacy_dispenses (visit_id)")
    op.execute("CREATE INDEX ix_pharmacy_dispenses_dispensed_by ON pharmacy_dispenses (dispensed_by)")

    # ---------------------------------------------------------------
    # pharmacy_dispense_items
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE pharmacy_dispense_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            dispense_id UUID NOT NULL REFERENCES pharmacy_dispenses(id) ON DELETE CASCADE,
            prescription_item_id UUID NOT NULL REFERENCES prescription_items(id),
            batch_id UUID NOT NULL REFERENCES inventory_batches(id),
            quantity_prescribed NUMERIC(12,2),
            quantity_dispensed NUMERIC(12,2),
            is_substitute BOOLEAN NOT NULL DEFAULT FALSE,
            substitute_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_pharmacy_dispense_items_dispense_id ON pharmacy_dispense_items (dispense_id)")
    op.execute("CREATE INDEX ix_pharmacy_dispense_items_prescription_item_id ON pharmacy_dispense_items (prescription_item_id)")
    op.execute("CREATE INDEX ix_pharmacy_dispense_items_batch_id ON pharmacy_dispense_items (batch_id)")

    # ---------------------------------------------------------------
    # grn [Blame]
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE grn (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            supplier_id UUID NOT NULL REFERENCES suppliers(id),
            invoice_number VARCHAR(50),
            received_date DATE NOT NULL,
            status VARCHAR(50) NOT NULL
                CONSTRAINT ck_grn_status
                CHECK (status IN ('draft','received','verified','cancelled')),
            created_by UUID NOT NULL REFERENCES users(id),
            updated_by UUID NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_grn_supplier_id ON grn (supplier_id)")
    op.execute("CREATE INDEX ix_grn_created_by ON grn (created_by)")
    op.execute("CREATE INDEX ix_grn_updated_by ON grn (updated_by)")

    # ---------------------------------------------------------------
    # grn_items
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE grn_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            grn_id UUID NOT NULL REFERENCES grn(id) ON DELETE CASCADE,
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            batch_number VARCHAR(50),
            expiry_date DATE,
            quantity NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC(12,2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_grn_items_grn_id ON grn_items (grn_id)")
    op.execute("CREATE INDEX ix_grn_items_item_id ON grn_items (item_id)")

    # ---------------------------------------------------------------
    # indents [Blame]
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE indents (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            department_id UUID NOT NULL REFERENCES departments(id),
            status VARCHAR(50) NOT NULL
                CONSTRAINT ck_indents_status
                CHECK (status IN ('requested','approved','rejected','issued')),
            approved_by UUID NULL REFERENCES users(id),
            created_by UUID NOT NULL REFERENCES users(id),
            updated_by UUID NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_indents_department_id ON indents (department_id)")
    op.execute("CREATE INDEX ix_indents_approved_by ON indents (approved_by)")
    op.execute("CREATE INDEX ix_indents_created_by ON indents (created_by)")
    op.execute("CREATE INDEX ix_indents_updated_by ON indents (updated_by)")

    # ---------------------------------------------------------------
    # indent_items
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE indent_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            indent_id UUID NOT NULL REFERENCES indents(id) ON DELETE CASCADE,
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            quantity_requested NUMERIC(12,2) NOT NULL CHECK (quantity_requested > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_indent_items_indent_id ON indent_items (indent_id)")
    op.execute("CREATE INDEX ix_indent_items_item_id ON indent_items (item_id)")

    # ---------------------------------------------------------------
    # adjustments [Blame] - dual sign-off
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE adjustments (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            batch_id UUID NOT NULL REFERENCES inventory_batches(id),
            quantity_change NUMERIC(12,2) NOT NULL CHECK (quantity_change <> 0),
            reason TEXT NOT NULL,
            first_approver_id UUID NOT NULL REFERENCES users(id),
            second_approver_id UUID NULL REFERENCES users(id),
            status VARCHAR(50) NOT NULL
                CONSTRAINT ck_adjustments_status
                CHECK (status IN ('pending','approved','rejected')),
            created_by UUID NOT NULL REFERENCES users(id),
            updated_by UUID NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_adjustments_distinct_approvers CHECK (first_approver_id <> second_approver_id)
        )
    """)
    op.execute("CREATE INDEX ix_adjustments_item_id ON adjustments (item_id)")
    op.execute("CREATE INDEX ix_adjustments_batch_id ON adjustments (batch_id)")
    op.execute("CREATE INDEX ix_adjustments_first_approver_id ON adjustments (first_approver_id)")
    op.execute("CREATE INDEX ix_adjustments_second_approver_id ON adjustments (second_approver_id)")
    op.execute("CREATE INDEX ix_adjustments_created_by ON adjustments (created_by)")
    op.execute("CREATE INDEX ix_adjustments_updated_by ON adjustments (updated_by)")

    # ---------------------------------------------------------------
    # facility_settings
    # ---------------------------------------------------------------
    op.execute("""
        CREATE TABLE facility_settings (
            facility_id UUID PRIMARY KEY REFERENCES facilities(id),
            stock_deduction_policy VARCHAR(50)
                CONSTRAINT ck_facility_settings_stock_deduction_policy
                CHECK (stock_deduction_policy IN ('on_acceptance','on_dispense')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS facility_settings")
    op.execute("DROP TABLE IF EXISTS adjustments")
    op.execute("DROP TABLE IF EXISTS indent_items")
    op.execute("DROP TABLE IF EXISTS indents")
    op.execute("DROP TABLE IF EXISTS grn_items")
    op.execute("DROP TABLE IF EXISTS grn")
    op.execute("DROP TABLE IF EXISTS pharmacy_dispense_items")
    op.execute("DROP INDEX IF EXISTS uq_pharmacy_dispenses_current")
    op.execute("DROP TABLE IF EXISTS pharmacy_dispenses")
