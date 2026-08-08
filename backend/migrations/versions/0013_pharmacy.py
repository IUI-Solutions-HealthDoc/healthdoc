import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pharmacy_dispenses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("prescription_id", UUID(as_uuid=True),
                  sa.ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("visit_id", UUID(as_uuid=True),
                  sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("dispensed_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('received','in_progress','partially_dispensed','dispensed',"
            "'out_of_stock','substitute_suggested','doctor_approval_required',"
            "'returned','cancelled')",
            name="ck_pharmacy_dispenses_status",
        ),
        sa.UniqueConstraint("prescription_id", "version",
                             name="uq_pharmacy_dispenses_prescription_id_version"),
    )
    op.execute("""
        CREATE UNIQUE INDEX uq_pharmacy_dispenses_current
        ON pharmacy_dispenses (prescription_id)
        WHERE is_current
    """)
    op.create_index("ix_pharmacy_dispenses_visit_id", "pharmacy_dispenses", ["visit_id"])
    op.create_index("ix_pharmacy_dispenses_dispensed_by", "pharmacy_dispenses", ["dispensed_by"])

    op.create_table(
        "pharmacy_dispense_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("dispense_id", UUID(as_uuid=True),
                  sa.ForeignKey("pharmacy_dispenses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prescription_item_id", UUID(as_uuid=True),
                  sa.ForeignKey("prescription_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("quantity_prescribed", sa.Numeric(12, 2)),
        sa.Column("quantity_dispensed", sa.Numeric(12, 2)),
        sa.Column("is_substitute", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("substitute_reason", sa.Text()),
        sa.Column("approval_status", sa.String(50), nullable=False, server_default="not_required"),
        sa.Column("substitute_item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("approved_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("expiry_override_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("expiry_override_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "approval_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="ck_pharmacy_dispense_items_approval_status",
        ),
        sa.CheckConstraint(
            "quantity_dispensed IS NULL OR quantity_dispensed >= 0",
            name="ck_pharmacy_dispense_items_quantity_dispensed_nonneg",
        ),
        sa.CheckConstraint(
            "quantity_dispensed IS NULL OR quantity_prescribed IS NULL "
            "OR quantity_dispensed <= quantity_prescribed",
            name="ck_pharmacy_dispense_items_dispensed_not_over_prescribed",
        ),
        sa.CheckConstraint(
            "NOT is_substitute OR substitute_reason IS NOT NULL",
            name="ck_pharmacy_dispense_items_substitute_reason_required",
        ),
    )
    op.create_index("ix_pharmacy_dispense_items_dispense_id", "pharmacy_dispense_items",
                    ["dispense_id"])
    op.create_index("ix_pharmacy_dispense_items_prescription_item_id", "pharmacy_dispense_items",
                    ["prescription_item_id"])
    op.create_index("ix_pharmacy_dispense_items_batch_id", "pharmacy_dispense_items",
                    ["batch_id"])
    op.create_index("ix_pharmacy_dispense_items_substitute_item_id", "pharmacy_dispense_items",
                    ["substitute_item_id"])

    op.execute("""
        CREATE OR REPLACE FUNCTION reject_expired_batch_dispense()
        RETURNS TRIGGER AS $$
        DECLARE
    batch_expiry DATE;
    fac_tz       TEXT;
BEGIN
    IF NEW.batch_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT b.expiry_date, f.timezone
      INTO batch_expiry, fac_tz
      FROM inventory_batches b
      JOIN stock_locations sl ON sl.id = b.stock_location_id
      JOIN facilities      f  ON f.id  = sl.facility_id
     WHERE b.id = NEW.batch_id;

    IF batch_expiry < (now() AT TIME ZONE fac_tz)::date THEN
                IF NEW.expiry_override_by IS NULL OR NEW.expiry_override_reason IS NULL THEN
                    RAISE EXCEPTION
                        'batch % expired % — dispensing requires expiry_override_by '
                        'and expiry_override_reason to be set',
                        NEW.batch_id, batch_expiry;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_pharmacy_dispense_items_reject_expired
        BEFORE INSERT OR UPDATE ON pharmacy_dispense_items
        FOR EACH ROW EXECUTE FUNCTION reject_expired_batch_dispense()
    """)

    op.create_table(
        "grn",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("supplier_id", UUID(as_uuid=True),
                  sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("invoice_number", sa.String(50)),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft','received','verified','cancelled')",
            name="ck_grn_status",
        ),
    )
    op.create_index("ix_grn_facility_id", "grn", ["facility_id"])
    op.create_index("ix_grn_supplier_id", "grn", ["supplier_id"])
    op.create_index("ix_grn_created_by", "grn", ["created_by"])
    op.create_index("ix_grn_updated_by", "grn", ["updated_by"])

    op.create_table(
        "grn_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("grn_id", UUID(as_uuid=True),
                  sa.ForeignKey("grn.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("batch_number", sa.String(50)),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_grn_items_quantity_positive"),
    )
    op.create_index("ix_grn_items_grn_id", "grn_items", ["grn_id"])
    op.create_index("ix_grn_items_item_id", "grn_items", ["item_id"])

    op.create_table(
        "indents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('requested','approved','rejected','issued')",
            name="ck_indents_status",
        ),
    )
    op.create_index("ix_indents_facility_id", "indents", ["facility_id"])
    op.create_index("ix_indents_department_id", "indents", ["department_id"])
    op.create_index("ix_indents_approved_by", "indents", ["approved_by"])
    op.create_index("ix_indents_created_by", "indents", ["created_by"])
    op.create_index("ix_indents_updated_by", "indents", ["updated_by"])

    op.create_table(
        "indent_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("indent_id", UUID(as_uuid=True),
                  sa.ForeignKey("indents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("quantity_requested", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity_requested > 0", name="ck_indent_items_quantity_requested_positive"),
    )
    op.create_index("ix_indent_items_indent_id", "indent_items", ["indent_id"])
    op.create_index("ix_indent_items_item_id", "indent_items", ["item_id"])

    op.create_table(
        "adjustments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("inventory_batches.id"), nullable=False),
        sa.Column("quantity_change", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("first_approver_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("second_approver_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("quantity_change <> 0", name="ck_adjustments_quantity_change_nonzero"),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_adjustments_status",
        ),
        sa.CheckConstraint(
            "first_approver_id <> second_approver_id",
            name="ck_adjustments_distinct_approvers",
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR second_approver_id IS NOT NULL",
            name="ck_adjustments_second_approver_required_when_approved",
        ),
        sa.CheckConstraint(
            "created_by <> first_approver_id",
            name="ck_adjustments_creator_not_first_approver",
        ),
        sa.CheckConstraint(
            "second_approver_id IS NULL OR created_by <> second_approver_id",
            name="ck_adjustments_creator_not_second_approver",
        ),
    )
    op.create_index("ix_adjustments_facility_id", "adjustments", ["facility_id"])
    op.create_index("ix_adjustments_item_id", "adjustments", ["item_id"])
    op.create_index("ix_adjustments_batch_id", "adjustments", ["batch_id"])
    op.create_index("ix_adjustments_first_approver_id", "adjustments", ["first_approver_id"])
    op.create_index("ix_adjustments_second_approver_id", "adjustments", ["second_approver_id"])
    op.create_index("ix_adjustments_created_by", "adjustments", ["created_by"])
    op.create_index("ix_adjustments_updated_by", "adjustments", ["updated_by"])

    op.create_table(
        "facility_settings",
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id"), primary_key=True),
        sa.Column("stock_deduction_policy", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "stock_deduction_policy IN ('on_acceptance','on_dispense')",
            name="ck_facility_settings_stock_deduction_policy",
        ),
    )


def downgrade() -> None:
    op.drop_table("facility_settings")
    op.drop_table("adjustments")
    op.drop_table("indent_items")
    op.drop_table("indents")
    op.drop_table("grn_items")
    op.drop_table("grn")

    op.execute("DROP TRIGGER IF EXISTS trg_pharmacy_dispense_items_reject_expired "
               "ON pharmacy_dispense_items")
    op.execute("DROP FUNCTION IF EXISTS reject_expired_batch_dispense()")
    op.drop_table("pharmacy_dispense_items")

    op.execute("DROP INDEX IF EXISTS uq_pharmacy_dispenses_current")
    op.drop_table("pharmacy_dispenses")
