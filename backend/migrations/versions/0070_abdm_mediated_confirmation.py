"""Persist M2 mediated-link confirmation acknowledgements before delivery."""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("abdm_callback_reply_kind", "abdm_callback_replies", type_="check")
    op.create_check_constraint(
        "abdm_callback_reply_kind",
        "abdm_callback_replies",
        "kind IN ('hip_consent','hip_request','hiu_consent','hip_link_confirm')",
    )


def downgrade() -> None:
    # Preserve committed proof/recovery evidence rather than deleting it to
    # satisfy the old CHECK. Empty-schema downgrade remains reversible.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_callback_replies "
        "WHERE kind = 'hip_link_confirm') THEN RAISE EXCEPTION "
        "'M2 confirmation evidence exists; reviewed recovery required'; END IF; END $$"
    )
    op.drop_constraint("abdm_callback_reply_kind", "abdm_callback_replies", type_="check")
    op.create_check_constraint(
        "abdm_callback_reply_kind",
        "abdm_callback_replies",
        "kind IN ('hip_consent','hip_request','hiu_consent')",
    )
