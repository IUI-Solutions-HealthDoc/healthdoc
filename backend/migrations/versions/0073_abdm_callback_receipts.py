"""Encrypted redacted HTTP callback receipts independent of clinical transactions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "abdm_callback_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("response_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("path", sa.String(250), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("evidence_encrypted", sa.LargeBinary(), nullable=False),
    )
    for name in ("expires_at", "request_id", "response_request_id"):
        op.create_index(f"ix_abdm_callback_receipts_{name}", "abdm_callback_receipts", [name])


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_callback_receipts) THEN "
               "RAISE EXCEPTION 'Callback receipts exist; reviewed recovery required'; END IF; END $$")
    op.drop_table("abdm_callback_receipts")
