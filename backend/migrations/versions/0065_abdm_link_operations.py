"""Separate token correlation from per-HI-type link-operation acknowledgement."""

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("abdm_care_context_links", sa.Column("token_request_id", sa.String(100)))
    op.add_column("abdm_care_context_links", sa.Column("link_token_encrypted", sa.LargeBinary()))
    op.add_column(
        "abdm_care_context_links", sa.Column("token_use_until", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_abdm_links_token_request", "abdm_care_context_links", ["token_request_id"], unique=True
    )
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind",
        "abdm_jobs",
        "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context')",
    )


def downgrade() -> None:
    # Refuse to discard undelivered link work in a downgrade. An operator must
    # finish/cancel it explicitly before an older worker can safely run.
    op.execute(
        "DELETE FROM abdm_jobs WHERE kind IN ('link_token','link_context') AND status = 'done'"
    )
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind", "abdm_jobs", "kind IN ('context_notify','hip_transfer','hip_notify')"
    )
    op.drop_index("ix_abdm_links_token_request", "abdm_care_context_links")
    op.drop_column("abdm_care_context_links", "token_use_until")
    op.drop_column("abdm_care_context_links", "link_token_encrypted")
    op.drop_column("abdm_care_context_links", "token_request_id")
