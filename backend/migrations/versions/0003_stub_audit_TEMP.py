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
