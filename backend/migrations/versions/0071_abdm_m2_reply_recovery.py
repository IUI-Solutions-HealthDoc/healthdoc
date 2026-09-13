"""Bounded encrypted M2 reply snapshots; preserve applied revision 0070."""

import sqlalchemy as sa
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("abdm_callback_replies", sa.Column("response_encrypted", sa.LargeBinary()))
    op.add_column(
        "abdm_callback_replies", sa.Column("response_expires_at", sa.DateTime(timezone=True))
    )
    op.drop_constraint("abdm_callback_reply_kind", "abdm_callback_replies", type_="check")
    op.create_check_constraint(
        "abdm_callback_reply_kind",
        "abdm_callback_replies",
        "kind IN ('hip_consent','hip_request','hiu_consent','hip_link_confirm',"
        "'hip_discover','hip_link_init','hip_link_reject','hip_profile')",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_callback_replies WHERE "
        "kind IN ('hip_discover','hip_link_init','hip_link_reject','hip_profile') "
        "OR response_encrypted IS NOT NULL) THEN RAISE EXCEPTION "
        "'M2 reply evidence exists; reviewed recovery required'; END IF; END $$"
    )
    op.drop_constraint("abdm_callback_reply_kind", "abdm_callback_replies", type_="check")
    op.create_check_constraint(
        "abdm_callback_reply_kind",
        "abdm_callback_replies",
        "kind IN ('hip_consent','hip_request','hiu_consent','hip_link_confirm')",
    )
    op.drop_column("abdm_callback_replies", "response_expires_at")
    op.drop_column("abdm_callback_replies", "response_encrypted")
