from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ALTER COLUMN batch_id DROP NOT NULL
    """)

    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ADD COLUMN approval_status VARCHAR(50) NOT NULL DEFAULT 'not_required'
            CONSTRAINT ck_pharmacy_dispense_items_approval_status
            CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected'))
    """)
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ADD COLUMN substitute_item_id UUID NULL REFERENCES inventory_items(id)
    """)
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ADD COLUMN approved_by UUID NULL REFERENCES users(id)
    """)
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ADD COLUMN approved_at TIMESTAMPTZ NULL
    """)
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ADD COLUMN rejection_reason TEXT NULL
    """)

    op.execute("""
        CREATE INDEX ix_pharmacy_dispense_items_approval_status
        ON pharmacy_dispense_items (approval_status)
        WHERE approval_status = 'pending'
    """)
    op.execute("""
        CREATE INDEX ix_pharmacy_dispense_items_substitute_item_id
        ON pharmacy_dispense_items (substitute_item_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pharmacy_dispense_items_substitute_item_id")
    op.execute("DROP INDEX IF EXISTS ix_pharmacy_dispense_items_approval_status")
    op.execute("ALTER TABLE pharmacy_dispense_items DROP COLUMN IF EXISTS rejection_reason")
    op.execute("ALTER TABLE pharmacy_dispense_items DROP COLUMN IF EXISTS approved_at")
    op.execute("ALTER TABLE pharmacy_dispense_items DROP COLUMN IF EXISTS approved_by")
    op.execute("ALTER TABLE pharmacy_dispense_items DROP COLUMN IF EXISTS substitute_item_id")
    op.execute("ALTER TABLE pharmacy_dispense_items DROP COLUMN IF EXISTS approval_status")
    # NOTE: does not restore batch_id's NOT NULL — any real 'pending' rows
    # written under 0014 would violate it. Downgrade only after confirming
    # no pending rows exist, or handle them (reject/delete) first.
    op.execute("""
        ALTER TABLE pharmacy_dispense_items
        ALTER COLUMN batch_id SET NOT NULL
    """)
