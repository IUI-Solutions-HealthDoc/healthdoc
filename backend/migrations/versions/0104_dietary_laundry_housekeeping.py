"""Kitchen diet orders and meals, laundry batches, housekeeping tasks; beds gain 'cleaning'.

Revision ID: 0104
Revises: 0103
Create Date: 2026-11-27

An admitted patient's food, their bed linen and the cleaning of the bed after
they leave had no record in HealthDoc. diet_orders holds the diet in force per
admission (one active at a time); meal_services each meal served, refused or
not served. linen_batches/items/events track linen out of a ward and counted
back. housekeeping_tasks holds cleaning work; discharge and transfer raise a
bed turnover task and put the bed in the new 'cleaning' status, which
admission does not offer, until housekeeping records it clean.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None

_DIET_TYPES = (
    "'normal', 'soft', 'liquid', 'clear_liquid', 'diabetic', 'renal', 'low_salt', 'low_fat', "
    "'high_protein', 'semi_solid', 'tube_feed', 'npo', 'other'"
)
_MEALS = "'early_morning', 'breakfast', 'mid_morning', 'lunch', 'evening_snack', 'dinner', 'bedtime'"
_LINEN = (
    "'bed_sheet', 'draw_sheet', 'pillow_cover', 'blanket', 'patient_gown', 'towel', 'curtain', 'ot_linen', 'other'"
)
_LINEN_STATUSES = "'collected', 'washing', 'ready', 'returned'"
_TASK_TYPES = "'bed_turnover', 'terminal_clean', 'routine_clean', 'spill', 'linen_change', 'other'"


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()"))


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.drop_constraint("ck_beds_status", "beds", type_="check")
    op.create_check_constraint(
        "ck_beds_status", "beds", "status IN ('vacant', 'occupied', 'reserved', 'maintenance', 'cleaning')"
    )

    op.create_table(
        "diet_orders",
        _id(),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("admission_id", UUID(as_uuid=True), sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("diet_type", sa.String(50), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("food_allergies", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ordered_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"diet_type IN ({_DIET_TYPES})", name="ck_diet_orders_diet_type"),
        sa.CheckConstraint("status IN ('active', 'stopped')", name="ck_diet_orders_status"),
        sa.CheckConstraint(
            "diet_type <> 'other' OR (instructions IS NOT NULL AND trim(instructions) <> '')",
            name="ck_diet_orders_other_needs_instructions",
        ),
        sa.CheckConstraint("status <> 'stopped' OR stopped_at IS NOT NULL", name="ck_diet_orders_stopped_at"),
    )
    op.create_index(
        "uq_diet_orders_active_admission", "diet_orders", ["admission_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_diet_orders_admission_id", "diet_orders", ["admission_id"])
    op.create_index("ix_diet_orders_facility_status", "diet_orders", ["facility_id", "status"])
    op.create_index("ix_diet_orders_ordered_by", "diet_orders", ["ordered_by"])
    op.create_index("ix_diet_orders_stopped_by", "diet_orders", ["stopped_by"])

    op.create_table(
        "meal_services",
        _id(),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("admission_id", UUID(as_uuid=True), sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("diet_order_id", UUID(as_uuid=True), sa.ForeignKey("diet_orders.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("meal", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_stamps(),
        sa.CheckConstraint(f"meal IN ({_MEALS})", name="ck_meal_services_meal"),
        sa.CheckConstraint("status IN ('served', 'refused', 'not_served')", name="ck_meal_services_status"),
        sa.CheckConstraint(
            "status <> 'not_served' OR (notes IS NOT NULL AND trim(notes) <> '')",
            name="ck_meal_services_not_served_reason",
        ),
    )
    op.create_index(
        "uq_meal_services_admission_day_meal", "meal_services", ["admission_id", "service_date", "meal"], unique=True
    )
    op.create_index("ix_meal_services_facility_day", "meal_services", ["facility_id", "service_date"])
    op.create_index("ix_meal_services_diet_order_id", "meal_services", ["diet_order_id"])
    op.create_index("ix_meal_services_recorded_by", "meal_services", ["recorded_by"])

    op.create_table(
        "linen_batches",
        _id(),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ward_id", UUID(as_uuid=True), sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("bed_id", UUID(as_uuid=True), sa.ForeignKey("beds.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("source", sa.String(120), nullable=True),
        sa.Column("is_infected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(50), nullable=False, server_default="collected"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("collected_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"status IN ({_LINEN_STATUSES})", name="ck_linen_batches_status"),
    )
    op.create_index("ix_linen_batches_facility_status", "linen_batches", ["facility_id", "status"])
    op.create_index("ix_linen_batches_ward_id", "linen_batches", ["ward_id"])
    op.create_index("ix_linen_batches_bed_id", "linen_batches", ["bed_id"])
    op.create_index("ix_linen_batches_collected_by", "linen_batches", ["collected_by"])

    op.create_table(
        "linen_batch_items",
        _id(),
        sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("linen_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("returned_quantity", sa.Integer(), nullable=True),
        sa.Column("condemned_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(f"item_type IN ({_LINEN})", name="ck_linen_batch_items_item_type"),
        sa.CheckConstraint("quantity > 0 AND quantity <= 1000", name="ck_linen_batch_items_quantity"),
        sa.CheckConstraint(
            "returned_quantity IS NULL OR (returned_quantity >= 0 AND condemned_quantity >= 0 "
            "AND returned_quantity + condemned_quantity <= quantity)",
            name="ck_linen_batch_items_counted_back",
        ),
    )
    op.create_index("uq_linen_batch_items_batch_type", "linen_batch_items", ["batch_id", "item_type"], unique=True)
    op.create_index("ix_linen_batch_items_facility_id", "linen_batch_items", ["facility_id"])

    op.create_table(
        "linen_batch_events",
        _id(),
        sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("linen_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"to_status IN ({_LINEN_STATUSES})", name="ck_linen_batch_events_to"),
    )
    op.create_index("ix_linen_batch_events_batch", "linen_batch_events", ["batch_id", "changed_at"])
    op.create_index("ix_linen_batch_events_facility_id", "linen_batch_events", ["facility_id"])
    op.create_index("ix_linen_batch_events_changed_by", "linen_batch_events", ["changed_by"])

    op.create_table(
        "housekeeping_tasks",
        _id(),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ward_id", UUID(as_uuid=True), sa.ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bed_id", UUID(as_uuid=True), sa.ForeignKey("beds.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("admission_id", UUID(as_uuid=True), sa.ForeignKey("admissions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(50), nullable=False, server_default="routine"),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("assigned_to_name", sa.String(120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("linen_changed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mattress_disinfected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("surfaces_disinfected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("waste_removed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("linen_batch_id", UUID(as_uuid=True), sa.ForeignKey("linen_batches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"task_type IN ({_TASK_TYPES})", name="ck_housekeeping_tasks_task_type"),
        sa.CheckConstraint("priority IN ('routine', 'urgent')", name="ck_housekeeping_tasks_priority"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'done', 'cancelled')", name="ck_housekeeping_tasks_status"
        ),
        sa.CheckConstraint("source IN ('discharge', 'transfer', 'manual')", name="ck_housekeeping_tasks_source"),
        sa.CheckConstraint(
            "status <> 'cancelled' OR (cancel_reason IS NOT NULL AND trim(cancel_reason) <> '')",
            name="ck_housekeeping_tasks_cancel_reason",
        ),
        sa.CheckConstraint("status <> 'done' OR completed_at IS NOT NULL", name="ck_housekeeping_tasks_completed_at"),
    )
    op.create_index(
        "uq_housekeeping_tasks_open_bed_turnover", "housekeeping_tasks", ["bed_id"], unique=True,
        postgresql_where=sa.text("task_type = 'bed_turnover' AND status IN ('pending', 'in_progress')"),
    )
    op.create_index("ix_housekeeping_tasks_facility_status", "housekeeping_tasks", ["facility_id", "status"])
    for column in (
        "ward_id", "bed_id", "admission_id", "linen_batch_id", "requested_by", "started_by", "completed_by",
    ):
        op.create_index(f"ix_housekeeping_tasks_{column}", "housekeeping_tasks", [column])


def downgrade() -> None:
    op.drop_table("housekeeping_tasks")
    op.drop_table("linen_batch_events")
    op.drop_table("linen_batch_items")
    op.drop_table("linen_batches")
    op.drop_table("meal_services")
    op.drop_table("diet_orders")
    # A bed waiting for cleaning is not occupied; vacant is the only status the
    # old constraint has for it.
    op.execute("UPDATE beds SET status = 'vacant' WHERE status = 'cleaning'")
    op.drop_constraint("ck_beds_status", "beds", type_="check")
    op.create_check_constraint(
        "ck_beds_status", "beds", "status IN ('vacant', 'occupied', 'reserved', 'maintenance')"
    )
