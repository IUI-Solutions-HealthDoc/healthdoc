"""Explicit professional identity and immutable HIU requester snapshots.

No guessed issuer, synthetic registration or backfill of historical requests.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("registration_identifier_type", sa.String(50)))
    op.add_column("users", sa.Column("registration_identifier_system", sa.String(255)))
    op.add_column("abdm_consent_requests", sa.Column("requester_snapshot", postgresql.JSONB()))


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM abdm_consent_requests "
        "WHERE requester_snapshot IS NOT NULL) OR EXISTS (SELECT 1 FROM users "
        "WHERE registration_identifier_type IS NOT NULL "
        "OR registration_identifier_system IS NOT NULL) THEN RAISE EXCEPTION "
        "'ABDM requester evidence exists; reviewed recovery required'; END IF; END $$"
    )
    op.drop_column("abdm_consent_requests", "requester_snapshot")
    op.drop_column("users", "registration_identifier_system")
    op.drop_column("users", "registration_identifier_type")
