"""0011_radiology

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import OrderStatus, ResultStatus

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # radiology_order_items
    op.create_table(
        "radiology_order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accession_number", sa.String(30), nullable=False, unique=True),
        sa.Column("modality", sa.String(30), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("machine_id", sa.String(50), nullable=True),
        sa.Column("pacs_study_uid", sa.String(100), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="placed"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_radiology_order_items_status", "radiology_order_items",
        OrderStatus.sql_check("status"),
    )
    op.create_index("ix_radiology_order_items_order_id", "radiology_order_items", ["order_id"])
    op.create_index("ix_radiology_order_items_created_by", "radiology_order_items", ["created_by"])

    # radiology_reports (append-only, versioned)
    op.create_table(
        "radiology_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("radiology_order_item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("radiology_order_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("findings", sa.Text(), nullable=False),
        sa.Column("impression", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_radiology_reports_status", "radiology_reports",
        ResultStatus.sql_check("status"),
    )
    op.create_unique_constraint(
        "uq_radiology_reports_version", "radiology_reports",
        ["radiology_order_item_id", "version"],
    )
    op.create_index(
        "uq_radiology_reports_current", "radiology_reports", ["radiology_order_item_id"],
        unique=True, postgresql_where=sa.text("is_current"),
    )
    op.create_index("ix_radiology_reports_created_by", "radiology_reports", ["created_by"])


def downgrade() -> None:
    op.drop_table("radiology_reports")
    op.drop_table("radiology_order_items")
