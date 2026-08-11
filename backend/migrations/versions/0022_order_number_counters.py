"""order_number_counters + orders.facility_id (denormalized, for audit auto-logging)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_number_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("facility_id", "counter_date", name="uq_order_number_counters_facility_id_counter_date"),
    )

    op.add_column("orders", sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        "UPDATE orders SET facility_id = encounters.facility_id "
        "FROM encounters WHERE encounters.id = orders.encounter_id"
    )
    op.alter_column("orders", "facility_id", nullable=False)
    op.create_foreign_key("fk_orders_facility_id", "orders", "facilities", ["facility_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_orders_facility_id", "orders", ["facility_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_facility_id", table_name="orders")
    op.drop_constraint("fk_orders_facility_id", "orders", type_="foreignkey")
    op.drop_column("orders", "facility_id")
    op.drop_table("order_number_counters")
