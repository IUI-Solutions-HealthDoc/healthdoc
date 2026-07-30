"""STUB - minimal audit_logs placeholder (TEMPORARY)

DELETE THIS FILE before opening your real PR for #167, once the real 0003
(audit, B7/Vani) migration lands. This only creates enough of audit_logs
to let pharmacy mutations write a real row locally instead of using the
no-op shim in service.py.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-25
"""
from alembic import op

revision = "0003_stub_TEMP"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id UUID NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id UUID,
            old_value JSONB,
            new_value JSONB
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs")
