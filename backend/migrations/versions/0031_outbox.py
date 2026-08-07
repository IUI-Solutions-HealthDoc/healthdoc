"""Migration 0031 — outbox_events + sequence (B1-W6-01, transactional outbox)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS seq_outbox")
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("sensitivity", sa.String(50), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("sequence", sa.BigInteger(), nullable=False,
                  server_default=sa.text("nextval('seq_outbox')")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sensitivity IN ('normal','important','critical')", name="ck_outbox_events_sensitivity"),
        sa.CheckConstraint("status IN ('pending','in_flight','sent','failed','dead_letter')", name="ck_outbox_events_status"),
    )
    op.create_index("ix_outbox_events_status_sequence", "outbox_events", ["status", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_sequence", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.execute("DROP SEQUENCE IF EXISTS seq_outbox")
