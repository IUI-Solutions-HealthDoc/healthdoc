"""0033 patient_merge_log decision_reason — PR review should-fix: reject_merge
previously overwrote the request's `reason` column with the rejection
reason, destroying why the merge was asked for. Both matter for audit.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'patient_merge_log',
        sa.Column('decision_reason', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('patient_merge_log', 'decision_reason')
