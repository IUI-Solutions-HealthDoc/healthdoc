"""Migration 0020 — notification_history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True),
                  sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_notification_history_department_id", "notification_history", ["department_id"])
    op.create_index(
        "ix_notification_history_payload", "notification_history", ["payload"],
        postgresql_using="gin", postgresql_ops={"payload": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_notification_history_payload", table_name="notification_history")
    op.drop_index("ix_notification_history_department_id", table_name="notification_history")
    op.drop_table("notification_history")
