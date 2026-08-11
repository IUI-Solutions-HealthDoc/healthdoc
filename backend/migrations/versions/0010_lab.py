"""0010_lab
Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import OrderStatus, ResultStatus

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # ---- lab_order_items ----
    op.create_table(
        "lab_order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accession_number", sa.String(30), nullable=False, unique=True),
        sa.Column("test_code", sa.String(30), nullable=True),
        sa.Column("test_name", sa.Text(), nullable=False),
        # varchar(50), not 30: sample_type is enum-backed, and §3's blanket
        # rule (v3.4.1) puts every enum-backed column at 50 so a later value
        # like 'cerebrospinal_fluid' doesn't need a migration to fit.
        sa.Column("sample_type", sa.String(50), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'placed'")
        ),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_lab_order_items_status", "lab_order_items",
        OrderStatus.sql_check("status"),
    )
    
    op.create_index("ix_lab_order_items_order_id", "lab_order_items", ["order_id"])
    op.create_index("ix_lab_order_items_department_id", "lab_order_items", ["department_id"])
    op.create_index("ix_lab_order_items_created_by", "lab_order_items", ["created_by"])

    # ---- lab_results (append-only, versioned) ----
    op.create_table(
        "lab_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("lab_order_item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("lab_order_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("result_data", postgresql.JSONB(), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_lab_results_status", "lab_results",
        ResultStatus.sql_check("status"),
    )
    # UNIQUE(lab_order_item_id, version) -- this also covers the FK index
    op.create_unique_constraint(
        "uq_lab_results_version", "lab_results", ["lab_order_item_id", "version"]
    )
    # Only ONE row per lab_order_item_id may be marked current at a time.
    op.create_index(
        "uq_lab_results_current", "lab_results", ["lab_order_item_id"],
        unique=True, postgresql_where=sa.text("is_current"),
    )
    op.create_index("ix_lab_results_created_by", "lab_results", ["created_by"])


def downgrade() -> None:
    op.drop_table("lab_results")
    op.drop_table("lab_order_items")
