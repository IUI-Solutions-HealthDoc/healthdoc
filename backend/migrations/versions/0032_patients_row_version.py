"""0032 patients row_version — optimistic concurrency (schema §4A.2)

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'patients',
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    op.drop_column('patients', 'row_version')
