"""Encrypt new external records in a consent-governed store, not the outbox.

Existing receipts are not retrospectively trusted or imported. Historical
outbox/Mongo copies require an explicitly reviewed inventory and cleanup.
"""

import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind",
        "abdm_jobs",
        "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context','hiu_notify','hiu_consent','hiu_request')",
    )
    op.add_column("abdm_received_bundles", sa.Column("content_encrypted", sa.LargeBinary()))
    op.add_column("abdm_received_bundles", sa.Column("content_key_version", sa.SmallInteger()))
    op.add_column("abdm_received_bundles", sa.Column("wire_sha256", sa.String(64)))
    op.add_column("abdm_received_bundles", sa.Column("source_hip_id", sa.String(120)))
    op.add_column("abdm_received_bundles", sa.Column("hi_type", sa.String(50)))
    op.add_column("abdm_received_bundles", sa.Column("document_at", sa.DateTime(timezone=True)))
    op.add_column("abdm_received_bundles", sa.Column("erased_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "abdm_received_content_key_pair",
        "abdm_received_bundles",
        "(content_encrypted IS NULL) = (content_key_version IS NULL)",
    )


def downgrade() -> None:
    # Refuse silent loss of live encrypted records. Erase/export them under the
    # approved retention policy before downgrading this data-bearing migration.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_received_bundles WHERE content_encrypted IS NOT NULL) THEN RAISE EXCEPTION 'Encrypted external records still exist'; END IF; END $$"
    )
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind",
        "abdm_jobs",
        "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context')",
    )
    op.drop_constraint("abdm_received_content_key_pair", "abdm_received_bundles", type_="check")
    for column in (
        "erased_at",
        "document_at",
        "hi_type",
        "source_hip_id",
        "wire_sha256",
        "content_key_version",
        "content_encrypted",
    ):
        op.drop_column("abdm_received_bundles", column)
