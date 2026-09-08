"""Commit acknowledgement intent before replying to ABDM; correlate artefact fetches."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind",
        "abdm_jobs",
        "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context','hiu_notify','hiu_consent','hiu_request','callback_ack','hiu_fetch')",
    )
    op.create_table(
        "abdm_callback_replies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("gateway_request_id", sa.String(100), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("subject_ids", postgresql.JSONB(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('hip_consent','hip_request','hiu_consent')", name="abdm_callback_reply_kind"
        ),
    )
    op.create_index(
        "ix_abdm_callback_replies_facility_id", "abdm_callback_replies", ["facility_id"]
    )


def downgrade() -> None:
    # Keep acknowledgement and correlation evidence; do not silently discard
    # these or orphan queued work during an application rollback.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_callback_replies) OR EXISTS (SELECT 1 FROM abdm_jobs WHERE kind IN ('callback_ack','hiu_fetch')) THEN RAISE EXCEPTION 'ABDM callback work exists; reviewed recovery required'; END IF; END $$"
    )
    op.drop_table("abdm_callback_replies")
    op.drop_constraint("abdm_job_kind", "abdm_jobs", type_="check")
    op.create_check_constraint(
        "abdm_job_kind",
        "abdm_jobs",
        "kind IN ('context_notify','hip_transfer','hip_notify','link_token','link_context','hiu_notify','hiu_consent','hiu_request')",
    )
