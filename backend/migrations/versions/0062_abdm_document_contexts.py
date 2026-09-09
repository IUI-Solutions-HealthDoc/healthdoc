"""Mark care contexts with their finalized document time, not visit time.

No automatic backfill: older references may mean a whole visit. An operator
must reconcile them to exact finalized source documents before sharing.
"""

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("abdm_care_contexts", sa.Column("document_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("abdm_care_contexts", "document_at")
