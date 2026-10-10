"""Control room: monitor scopes and 15-minute facility pulse.

Revision ID: 0097
Revises: 0096
Create Date: 2026-10-10

A state or district officer (realm role `monitor`) sees facilities inside the
area granted in monitor_scopes, and only the counts in facility_pulse: no
patient identifiers. The board reads these captures, never the clinical
tables, so its load does not grow with the number of officers looking.
Design: docs/control-room-design-2026-10-10.md.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None

_COUNTS = (
    "opd_today",
    "queue_waiting",
    "emergency_open",
    "admitted_now",
    "beds_total",
    "lab_pending",
    "stock_below_reorder",
    "batches_expiring_30d",
    "staff_rostered_today",
)


def upgrade() -> None:
    op.create_table(
        "monitor_scopes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("keycloak_sub", sa.String(64), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("state_code", sa.String(5), nullable=False),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("granted_by_sub", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("keycloak_sub", "state_code", "district", name="uq_monitor_scopes_sub_area"),
        sa.CheckConstraint("district IS NULL OR trim(district) <> ''", name="ck_monitor_scopes_district"),
    )
    op.create_index("ix_monitor_scopes_keycloak_sub", "monitor_scopes", ["keycloak_sub"])
    # NULL <> NULL: the unique constraint above does not stop two whole-state
    # grants for one officer, so a partial index does.
    op.create_index(
        "uq_monitor_scopes_sub_whole_state",
        "monitor_scopes",
        ["keycloak_sub", "state_code"],
        unique=True,
        postgresql_where=sa.text("district IS NULL"),
    )
    op.create_table(
        "facility_pulse",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "facility_id",
            UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opd_today", sa.Integer(), nullable=False),
        sa.Column("queue_waiting", sa.Integer(), nullable=False),
        sa.Column("emergency_open", sa.Integer(), nullable=False),
        sa.Column("admitted_now", sa.Integer(), nullable=False),
        sa.Column("beds_total", sa.Integer(), nullable=False),
        sa.Column("lab_pending", sa.Integer(), nullable=False),
        sa.Column("stock_below_reorder", sa.Integer(), nullable=False),
        sa.Column("batches_expiring_30d", sa.Integer(), nullable=False),
        sa.Column("staff_rostered_today", sa.Integer(), nullable=False),
        *(sa.CheckConstraint(f"{name} >= 0", name=f"ck_facility_pulse_{name}") for name in _COUNTS),
    )
    op.create_index(
        "ix_facility_pulse_facility_captured", "facility_pulse", ["facility_id", "captured_at"]
    )


def downgrade() -> None:
    op.drop_table("facility_pulse")
    op.drop_table("monitor_scopes")
