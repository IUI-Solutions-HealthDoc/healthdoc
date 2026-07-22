"""Migration — queues, queue_tokens."""

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
        sa.Column("now_serving_token_id", UUID(as_uuid=True), sa.ForeignKey("queue_tokens.id"), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("department_id", "doctor_user_id", "service_date", name="uq_queue_doctor_date"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "queue_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id"), nullable=False),
        sa.Column("visit_id", UUID(as_uuid=True), sa.ForeignKey("visits.id"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("token_display", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="waiting"),
        sa.Column("priority", sa.String(30), nullable=False, server_default="normal"),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("queue_id", "sequence", name="uq_queue_token_sequence"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("queue_tokens")
    op.drop_table("queues")
