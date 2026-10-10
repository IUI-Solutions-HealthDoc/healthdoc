"""Equipment register, status history, and equipment counts in the control room.

Revision ID: 0100
Revises: 0099
Create Date: 2026-10-10

"Is the machine working?" had no answer in HealthDoc: there was no register.
equipment holds each machine and its current status; equipment_status_events
keeps every change with who, when and why, so "down since" is recorded, not
inferred. facility_pulse gains the two counts the board colours by: any machine
down is amber, a critical one (ventilator, oxygen plant, generator) is red.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None

_STATUSES = "'working', 'down', 'maintenance', 'retired'"
_CATEGORIES = (
    "'imaging', 'laboratory', 'life_support', 'monitoring', 'surgical', 'sterilisation', 'power', "
    "'cold_chain', 'other'"
)


def upgrade() -> None:
    op.create_table(
        "equipment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column("asset_tag", sa.String(60), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(50), nullable=False, server_default="working"),
        sa.Column("status_since", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_equipment_status"),
        sa.CheckConstraint(f"category IN ({_CATEGORIES})", name="ck_equipment_category"),
        sa.CheckConstraint("trim(name) <> ''", name="ck_equipment_name"),
        sa.UniqueConstraint("facility_id", "asset_tag", name="uq_equipment_facility_asset_tag"),
    )
    op.create_index("ix_equipment_facility_status", "equipment", ["facility_id", "status"])
    op.create_index("ix_equipment_created_by", "equipment", ["created_by"])
    op.create_table(
        "equipment_status_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("equipment_id", UUID(as_uuid=True), sa.ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"to_status IN ({_STATUSES})", name="ck_equipment_status_events_to"),
    )
    op.create_index(
        "ix_equipment_status_events_equipment", "equipment_status_events", ["equipment_id", "changed_at"]
    )
    op.create_index("ix_equipment_status_events_facility_id", "equipment_status_events", ["facility_id"])
    op.create_index("ix_equipment_status_events_changed_by", "equipment_status_events", ["changed_by"])
    op.add_column("facility_pulse", sa.Column("equipment_down", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "facility_pulse", sa.Column("critical_equipment_down", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("facility_pulse", "critical_equipment_down")
    op.drop_column("facility_pulse", "equipment_down")
    op.drop_table("equipment_status_events")
    op.drop_table("equipment")
