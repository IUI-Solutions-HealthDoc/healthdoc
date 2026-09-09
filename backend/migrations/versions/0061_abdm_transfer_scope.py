"""Preserve the original data request interval across async HIP delivery.

Old rows intentionally retain NULL scope. The original requested interval was
discarded; copying the consent interval would silently authorize extra data.
They require a fresh request rather than a guessed backfill.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("abdm_hip_hi_requests", sa.Column("requested_from", sa.DateTime(timezone=True)))
    op.add_column("abdm_hip_hi_requests", sa.Column("requested_to", sa.DateTime(timezone=True)))
    op.add_column(
        "abdm_hip_hi_requests", sa.Column("requested_hi_types", postgresql.JSONB(none_as_null=True))
    )
    op.create_check_constraint(
        "abdm_hip_request_scope",
        "abdm_hip_hi_requests",
        "(requested_from IS NULL AND requested_to IS NULL AND requested_hi_types IS NULL) "
        "OR (requested_from IS NOT NULL AND requested_to IS NOT NULL "
        "AND requested_hi_types IS NOT NULL AND requested_from <= requested_to)",
    )


def downgrade() -> None:
    op.drop_constraint("abdm_hip_request_scope", "abdm_hip_hi_requests", type_="check")
    op.drop_column("abdm_hip_hi_requests", "requested_hi_types")
    op.drop_column("abdm_hip_hi_requests", "requested_to")
    op.drop_column("abdm_hip_hi_requests", "requested_from")
