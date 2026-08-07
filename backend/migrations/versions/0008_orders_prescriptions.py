"""0008_orders_prescriptions

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-23

Builds: orders, prescriptions, prescription_items (schema.md §3, migration 0008)
Depends on: 0007 visits/encounters.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------- orders
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default="routine"),
        sa.Column("status", sa.String(50), nullable=False, server_default="placed"),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
        sa.CheckConstraint(
            "order_type IN ('lab','radiology','pharmacy','procedure','blood')",
            name="ck_orders_order_type",
        ),
        sa.CheckConstraint("priority IN ('routine','urgent','stat')", name="ck_orders_priority"),
        sa.CheckConstraint(
            "status IN ('placed','in_progress','completed','cancelled')", name="ck_orders_status"
        ),
    )
    op.create_index("ix_orders_order_type_status", "orders", ["order_type", "status"])
    op.create_index("ix_orders_patient_id", "orders", ["patient_id"])
    op.create_index("ix_orders_encounter_id", "orders", ["encounter_id"])

    # ---------------------------------------------------- prescriptions
    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )
    op.create_index("ix_prescriptions_encounter_id", "prescriptions", ["encounter_id"])
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])

    # ----------------------------------------------- prescription_items
    op.create_table(
        "prescription_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("uuid_generate_v4()")),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("medicine_item_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK added in 0012
        sa.Column("medicine_name", sa.Text, nullable=False),
        sa.Column("dosage", sa.String(50), nullable=True),
        sa.Column("frequency", sa.String(50), nullable=True),
        sa.Column("duration_days", sa.Integer, nullable=True),
        sa.Column("route", sa.String(30), nullable=True),
        sa.Column("instructions", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="prescribed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('prescribed','dispensed','partially_dispensed','on_hold','cancelled')",
            name="ck_prescription_items_status",
        ),
    )
    op.create_index("ix_prescription_items_prescription_id", "prescription_items", ["prescription_id"])


def downgrade() -> None:
    op.drop_table("prescription_items")
    op.drop_table("prescriptions")
    op.drop_table("orders")