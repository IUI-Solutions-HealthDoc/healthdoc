"""0035 patients row_version — optimistic concurrency (schema §4A.2)

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'patients',
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    op.drop_column('patients', 'row_version')
