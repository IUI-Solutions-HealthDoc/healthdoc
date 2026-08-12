"""0033 charge_master — effective-dated tariff catalogue + the double-billing guard.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-03

Schema v3.14 §3 0033.

Before this, `invoice_items.unit_price` was typed by whoever created the line. Two clerks
charged different amounts for the same test, "what was the tariff on 12 March" had no
answer, and PM-JAY rates — which are mandated, not suggested — could not be enforced,
making an overcharge a compliance breach rather than a pricing mistake.

Prices are effective-dated and never UPDATEd: a revision inserts a new row. That is what
makes price history reconstructible for any past date, which is what an audit asks for.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charge_master",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),

        # Stable across price changes — this is what an invoice line refers to
        # conceptually, while charge_master_id pins the exact tariff row used.
        sa.Column("charge_code", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("charge_category", sa.String(50), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),

        # NULL = general tariff. 'PMJAY' etc. = scheme rate, which wins when the
        # invoice carries that scheme_code.
        sa.Column("scheme_code", sa.String(30), nullable=True),

        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),

        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        sa.CheckConstraint("unit_price >= 0", name="ck_charge_master_unit_price_non_negative"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_charge_master_effective_range"),
        sa.CheckConstraint(
            "charge_category IN ('registration','consultation','lab','radiology',"
            "'pharmacy','procedure','ipd_stay','blood','other')",
            name="ck_charge_master_charge_category"),
        sa.UniqueConstraint("facility_id", "charge_code", "scheme_code", "effective_from",
                            name="uq_charge_master_version"),
    )

    # The accrual lookup: newest tariff at or before the service date.
    op.create_index(
        "ix_charge_master_lookup", "charge_master",
        ["facility_id", "charge_code", "scheme_code", sa.text("effective_from DESC")],
    )

    op.add_column(
        "invoice_items",
        sa.Column("charge_master_id", UUID(as_uuid=True),
                  sa.ForeignKey("charge_master.id", ondelete="RESTRICT"), nullable=True),
    )
    op.create_index("ix_invoice_items_charge_master_id", "invoice_items", ["charge_master_id"])

    # ------------------------------------------------------------------
    # The most important line in this migration.
    #
    # Without it, a lab result finalised twice bills the patient twice, and nothing
    # anywhere prevents that. With it, the accrual service is safe to retry — which it
    # must be, because it runs on flaky rural links and after crash recovery.
    #
    # Partial: hand-entered lines legitimately have no source row, and NULLs would
    # otherwise all collide.
    # ------------------------------------------------------------------
    op.create_index(
        "uq_invoice_items_source", "invoice_items",
        ["invoice_id", "reference_type", "reference_id"],
        unique=True,
        postgresql_where=sa.text("reference_type IS NOT NULL AND reference_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_items_source", table_name="invoice_items")
    op.drop_index("ix_invoice_items_charge_master_id", table_name="invoice_items")
    op.drop_column("invoice_items", "charge_master_id")
    op.drop_index("ix_charge_master_lookup", table_name="charge_master")
    op.drop_table("charge_master")
