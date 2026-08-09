"""billing — invoices, invoice_items, payments, refunds, billing_counters

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-04

Owner: B7 (B7-W1-03 / B7-W3-01). Schema doc: HealthDoc_Database_Schema_v3_4 §3 "0014 — billing".


1. The doc says invoice_items are "frozen by the parent's trigger once
   invoice leaves draft" — built as a SECOND trigger on invoice_items
   that looks up the parent invoice's current status and blocks
   UPDATE/DELETE once that parent isn't 'draft' anymore. This is my
   reading of "the parent's trigger" (a second trigger enforcing the
   same rule, not literally the same trigger object, since Postgres
   triggers are per-table) — flag for confirmation.

2. CHECK constraints use literal value lists, not EnumClass.sql_check().
   app/common/enums.py is outside this task's scope, so no new enum
   classes (InvoiceStatus/PaymentMode/PaymentStatus/ChargeCategory) were
   added here. Whoever owns enums.py can add them later and this
   migration's CHECK constraints can be swapped to EnumClass.sql_check()
   in a follow-up — doesn't block this PR.

3. (B7-W3-01, #188) payments/refunds get an UNCONDITIONAL block trigger
   — no exception for any column, unlike invoices/invoice_items which
   stay mutable on status/updated_at/updated_by. Per architecture doc
   §22.3/§35.4.4: "payment receipt is immutable after finalization,
   corrections are reversal entries (refunds), never an edit." A refund
   never edits the payment it reverses either — it's its own append-only
   row. See item 8 below.

REMINDER (from the schema doc itself): "B7: unit-test that a payment can
flip status on an issued invoice before merging 0014." Done — see
backend/tests/billing/test_billing_triggers.py and
test_billing_flows.py. Also tested: UPDATE/DELETE on payments/refunds
raise (item 8), conditional freeze on invoices/invoice_items.

PR REVIEW FIXES (2 days ago, solutionsiui) applied in this revision:
  - CHECK constraints for charge_category/mode/status now generated
    from app.common.enums.{ChargeCategory,PaymentMode,PaymentStatus}
    .sql_check() instead of hardcoded literal lists, so the DB
    constraint and the enum class can't drift apart. invoices.status
    is intentionally NOT swapped — no matching enum export was asked
    for there, only a like-for-like 1:1 swap where one already exists.
  - sensitivity / scheme_code widened varchar(30) -> varchar(50), repo
    blanket rule for enum/status-ish columns (matches
    audit_log_archive.verification_status's width elsewhere).
  - invoices.row_version added (§4A optimistic concurrency) — see
    models.py's Invoice docstring for how it's used.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import ChargeCategory, PaymentMode, PaymentStatus

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. invoices
    # ------------------------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("invoice_number", sa.String(30), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("visits.id", ondelete="RESTRICT", name="fk_invoices_visit_id"),
                  nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT", name="fk_invoices_patient_id"),
                  nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_invoices_facility_id"),
                  nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("gross_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("scheme_adjustment", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("scheme_code", sa.String(50), nullable=True),
        sa.Column("sensitivity", sa.String(50), nullable=False, server_default="critical"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_invoices_created_by"),
                  nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_invoices_updated_by"),
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
        sa.CheckConstraint(
            "status IN ('draft','issued','partially_paid','paid','waived','cancelled')",
            name="ck_invoices_status",
        ),
        sa.CheckConstraint("net_amount >= 0", name="ck_invoices_net_amount_non_negative"),
    )
    op.create_index("ix_invoices_visit_id", "invoices", ["visit_id"])
    op.create_index("ix_invoices_patient_id", "invoices", ["patient_id"])
    op.create_index("ix_invoices_facility_id", "invoices", ["facility_id"])

    # ------------------------------------------------------------------
    # 2. invoice_items
    # ------------------------------------------------------------------
    op.create_table(
        "invoice_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id", ondelete="RESTRICT", name="fk_invoice_items_invoice_id"),
                  nullable=False),
        sa.Column("charge_category", sa.String(50), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(ChargeCategory.sql_check("charge_category"), name="ck_invoice_items_charge_category"),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_invoice_items_unit_price_non_negative"),
        sa.CheckConstraint("amount >= 0", name="ck_invoice_items_amount_non_negative"),
    )
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])
    # The constraint that makes _insert_invoice_item's dedupe real. Without
    # it, two concurrent build_invoice() calls both find the same unbilled
    # charge, both insert it, and the patient is billed twice for one lab
    # test — the IntegrityError that function catches can never be raised,
    # so its SAVEPOINT does nothing.
    #
    # PARTIAL, because reference_type/reference_id are nullable: manually
    # added invoice lines have no source charge to deduplicate against, and
    # NULLs must not collide with each other.
    #
    # This was originally deferred to a later migration. It belongs here —
    # invoice_items is created by this migration, and "we'll enforce it
    # later" for double-billing means shipping the double-billing.
    op.create_index(
        "uq_invoice_items_invoice_reference",
        "invoice_items",
        ["invoice_id", "reference_type", "reference_id"],
        unique=True,
        postgresql_where=sa.text("reference_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 3. payments
    # ------------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("receipt_number", sa.String(30), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id", ondelete="RESTRICT", name="fk_payments_invoice_id"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="INR"),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="success"),
        sa.Column("collected_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_payments_collected_by"),
                  nullable=False),
        sa.Column("collected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("sensitivity", sa.String(50), nullable=False, server_default="critical"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_payments_created_by"),
                  nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_payments_updated_by"),
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("receipt_number", name="uq_payments_receipt_number"),
        sa.CheckConstraint(PaymentMode.sql_check("mode"), name="ck_payments_mode"),
        sa.CheckConstraint(PaymentStatus.sql_check("status"), name="ck_payments_status"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("ix_payments_collected_by", "payments", ["collected_by"])

    # ------------------------------------------------------------------
    # 4. refunds
    # ------------------------------------------------------------------
    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("refund_number", sa.String(30), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("payments.id", ondelete="RESTRICT", name="fk_refunds_payment_id"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_refunds_approved_by"),
                  nullable=False),
        sa.Column("refunded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_refunds_created_by"),
                  nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_refunds_updated_by"),
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("refund_number", name="uq_refunds_refund_number"),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_approved_by", "refunds", ["approved_by"])

    # ------------------------------------------------------------------
    # 5. billing_counters
    # ------------------------------------------------------------------
    op.create_table(
        "billing_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_billing_counters_facility_id"),
                  nullable=False),
        sa.Column("counter_type", sa.String(50), nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "facility_id", "counter_type", "counter_date",
            name="uq_billing_counters_facility_type_date",
        ),
        sa.CheckConstraint("counter_type IN ('invoice','receipt','refund')", name="ck_billing_counters_counter_type"),
    )
    op.create_index("ix_billing_counters_facility_id", "billing_counters", ["facility_id"])

    # ------------------------------------------------------------------
    # 6. trg_invoices_freeze — the trigger the schema doc names by name.
    #    Raw SQL: Alembic autogenerate can't produce trigger DDL.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_invoices_freeze_fn() RETURNS trigger AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM 'draft' THEN
                IF (NEW.invoice_number, NEW.visit_id, NEW.patient_id, NEW.facility_id,
                    NEW.gross_amount, NEW.discount_amount, NEW.scheme_adjustment,
                    NEW.net_amount, NEW.scheme_code)
                   IS DISTINCT FROM
                   (OLD.invoice_number, OLD.visit_id, OLD.patient_id, OLD.facility_id,
                    OLD.gross_amount, OLD.discount_amount, OLD.scheme_adjustment,
                    OLD.net_amount, OLD.scheme_code)
                THEN
                    RAISE EXCEPTION
                        'invoices: cannot change frozen columns once an invoice leaves draft status (id=%)',
                        OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_invoices_freeze
        BEFORE UPDATE ON invoices
        FOR EACH ROW EXECUTE FUNCTION trg_invoices_freeze_fn();
        """
    )

    # ------------------------------------------------------------------
    # 7. invoice_items freeze — "frozen by the parent's trigger" per the
    #    schema doc. Built as a second trigger that checks the PARENT
    #    invoice's status, since invoice_items has no status column of
    #    its own to check against.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_invoice_items_freeze_fn() RETURNS trigger AS $$
        DECLARE
            parent_status varchar(50);
        BEGIN
            SELECT status INTO parent_status FROM invoices WHERE id = OLD.invoice_id;
            IF parent_status IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION
                    'invoice_items: cannot change or delete a line item once the parent invoice leaves draft status (invoice_id=%)',
                    OLD.invoice_id;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_invoice_items_freeze
        BEFORE UPDATE OR DELETE ON invoice_items
        FOR EACH ROW EXECUTE FUNCTION trg_invoice_items_freeze_fn();
        """
    )

    # ------------------------------------------------------------------
    # 8. payments / refunds — UNCONDITIONAL block (B7-W3-01, #188).
    #    Unlike 6/7 above, there's no "still draft" exception here —
    #    a payment/refund row never changes after insert, period.
    #    Corrections are a new refund row, not an edit.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_payments_block_fn() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'payments: rows are immutable after insert (id=%)', OLD.id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payments_block
        BEFORE UPDATE OR DELETE ON payments
        FOR EACH ROW EXECUTE FUNCTION trg_payments_block_fn();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_refunds_block_fn() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'refunds: rows are immutable after insert (id=%)', OLD.id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refunds_block
        BEFORE UPDATE OR DELETE ON refunds
        FOR EACH ROW EXECUTE FUNCTION trg_refunds_block_fn();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_refunds_block ON refunds;")
    op.execute("DROP FUNCTION IF EXISTS trg_refunds_block_fn();")
    op.execute("DROP TRIGGER IF EXISTS trg_payments_block ON payments;")
    op.execute("DROP FUNCTION IF EXISTS trg_payments_block_fn();")

    op.execute("DROP TRIGGER IF EXISTS trg_invoice_items_freeze ON invoice_items;")
    op.execute("DROP FUNCTION IF EXISTS trg_invoice_items_freeze_fn();")
    op.execute("DROP TRIGGER IF EXISTS trg_invoices_freeze ON invoices;")
    op.execute("DROP FUNCTION IF EXISTS trg_invoices_freeze_fn();")

    op.drop_index("ix_billing_counters_facility_id", table_name="billing_counters")
    op.drop_table("billing_counters")

    op.drop_index("ix_refunds_approved_by", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")

    op.drop_index("ix_payments_collected_by", table_name="payments")
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("uq_invoice_items_invoice_reference", table_name="invoice_items")
    op.drop_index("ix_invoice_items_invoice_id", table_name="invoice_items")
    op.drop_table("invoice_items")

    op.drop_index("ix_invoices_facility_id", table_name="invoices")
    op.drop_index("ix_invoices_patient_id", table_name="invoices")
    op.drop_index("ix_invoices_visit_id", table_name="invoices")
    op.drop_table("invoices")
