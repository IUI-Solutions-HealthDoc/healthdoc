"""Migration 0009— queues, queue_tokens."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from app.common.enums import QueuePriority, QueueTokenStatus


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rosters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("staff_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("shift", sa.String(50), nullable=False),
        sa.Column("roster_date", sa.Date(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("staff_user_id", "roster_date", "shift", name="uq_roster_staff_date_shift"),
    )
    op.create_index("ix_rosters_department_id", "rosters", ["department_id"])
    op.create_index("ix_rosters_room_id", "rosters", ["room_id"])


    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id"), nullable=False),          
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("doctor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("display_label", sa.String(50), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("department_id", "doctor_user_id", "service_date", name="uq_queue_doctor_date"),
    )

    op.create_index("ix_queues_facility_id", "queues", ["facility_id"])
    op.create_index("ix_queues_doctor_user_id", "queues", ["doctor_user_id"])
    op.create_index("ix_queues_room_id", "queues", ["room_id"])
    op.create_index("ix_queues_department_id_service_date", "queues", ["department_id", "service_date"])


    op.create_table(
        "queue_counters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("department_id", "counter_date", name="uq_queue_counter_department_date"),
    )


    op.create_table(
        "queue_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", UUID(as_uuid=True), sa.ForeignKey("facilities.id"), nullable=False),          
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id"), nullable=False),
        sa.Column("visit_id", UUID(as_uuid=True), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("token_display", sa.String(20), nullable=False),
        sa.Column("initial_priority", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="waiting"),
        sa.Column("priority", sa.String(50), nullable=False, server_default="normal"),
        sa.Column("priority_rank", sa.SmallInteger(), nullable=False, server_default="6"),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("queue_id", "sequence", name="uq_queue_token_sequence"),

        sa.CheckConstraint(QueueTokenStatus.sql_check("status"), name="ck_queue_tokens_status"),
        sa.CheckConstraint(QueuePriority.sql_check("priority"), name="ck_queue_tokens_priority"),
    )

    op.create_index("ix_queue_tokens_facility_id", "queue_tokens", ["facility_id"])
    op.create_index("ix_queue_tokens_visit_id", "queue_tokens", ["visit_id"])
    op.create_index(
        "ix_queue_tokens_active", "queue_tokens", ["queue_id", "priority_rank", "created_at"],
        postgresql_where=sa.text("status IN ('waiting','called')"),
    )

    op.create_index(
        "uq_queue_tokens_one_live_per_visit", "queue_tokens", ["visit_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed','cancelled','no_show')"),
    )

    op.add_column(
        "queues",
        sa.Column("now_serving_token_id", UUID(as_uuid=True), sa.ForeignKey("queue_tokens.id"), nullable=True),
    )

    op.create_index("ix_queues_now_serving_token_id", "queues", ["now_serving_token_id"])


    op.create_table(
        "queue_token_priority_changes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("queue_token_id", UUID(as_uuid=True), sa.ForeignKey("queue_tokens.id"), nullable=False),
        sa.Column("from_priority", sa.String(50), nullable=False),
        sa.Column("to_priority", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_queue_token_priority_changes_queue_token_id", "queue_token_priority_changes", ["queue_token_id"])
    op.create_index(
        "ix_queue_token_priority_changes_changed_by_changed_at",
        "queue_token_priority_changes", ["changed_by", "changed_at"],
    )


def downgrade() -> None:
    op.drop_table("queue_token_priority_changes")
    op.drop_index("ix_queues_now_serving_token_id", table_name="queues")
    op.drop_column("queues", "now_serving_token_id")
    op.drop_index("uq_queue_tokens_one_live_per_visit", table_name="queue_tokens")
    op.drop_index("ix_queue_tokens_active", table_name="queue_tokens")
    op.drop_table("queue_tokens")
    op.drop_table("queue_counters")
    op.drop_table("queues")
    op.drop_table("rosters")
