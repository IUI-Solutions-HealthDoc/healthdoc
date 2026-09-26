"""Allow historical ABDM jobs to be frozen during a service-ID cutover.

Revision ID: 0088
Revises: 0087
Create Date: 2026-09-26
"""

from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("abdm_job_status", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_status",
        "abdm_jobs",
        "status IN ('pending','leased','done','dead','frozen')",
    )


def downgrade() -> None:
    # PostgreSQL refuses the old constraint while frozen rows remain. That is
    # intentional: silently making them retryable would send old work under a
    # different registered service identity.
    op.drop_constraint("abdm_job_status", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_status",
        "abdm_jobs",
        "status IN ('pending','leased','done','dead')",
    )
