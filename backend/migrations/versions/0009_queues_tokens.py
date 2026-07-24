"""Migration 0009— queues, queue_tokens."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
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

    op.create_index("ix_queues_doctor_user_id", "queues", ["doctor_user_id"])
    op.create_index("ix_queues_room_id", "queues", ["room_id"])
    op.create_index("ix_queues_department_id_service_date", "queues", ["department_id", "service_date"])

    op.create_table(
        "queue_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id"), nullable=False),
        sa.Column("visit_id", UUID(as_uuid=True), sa.ForeignKey("visits.id"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("token_display", sa.String(20), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="waiting"),
        sa.Column("priority", sa.String(50), nullable=False, server_default="normal"),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("queue_id", "sequence", name="uq_queue_token_sequence"),

        sa.CheckConstraint(
            "status IN ('waiting','called','in_service','skipped','no_show','recalled','transferred','completed','cancelled')",
            name="status",
        ),
        sa.CheckConstraint(
            "priority IN ('normal','senior_citizen','pregnant','emergency','follow_up_recall','doctor_recall','admin_override')",
            name="priority",
        ),
    )

    op.create_index("ix_queue_tokens_visit_id", "queue_tokens", ["visit_id"])
    op.create_index(
        "ix_queue_tokens_active", "queue_tokens", ["queue_id", "priority", "created_at"],
        postgresql_where=sa.text("status IN ('waiting','called')"),
    )

    op.add_column(
        "queues",
        sa.Column("now_serving_token_id", UUID(as_uuid=True), sa.ForeignKey("queue_tokens.id"), nullable=True),
    )

    op.create_index("ix_queues_now_serving_token_id", "queues", ["now_serving_token_id"])


def downgrade() -> None:
    op.drop_index("ix_queues_now_serving_token_id", table_name="queues")
    op.drop_column("queues", "now_serving_token_id")
    op.drop_table("queue_tokens")
    op.drop_table("queues")
