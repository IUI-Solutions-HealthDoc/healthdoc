"""0036 patient_merge_log decision_reason — reject_merge previously overwrote
the request reason column with the rejection reason, destroying why the merge
was asked for. Both matter for audit — kept separate.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'patient_merge_log',
        sa.Column('decision_reason', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('patient_merge_log', 'decision_reason')
