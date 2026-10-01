"""Record whether a facility is government or private.

Revision ID: 0090
Revises: 0089
Create Date: 2026-10-01

ABDM's published ABHA consent (M1 CRT_ABHA_102) differs by ownership: NHA
tells private entities to remove the word "government" from two statements.
`facility_type` (phc, chc, hospital...) does not say which, so the consent
wording had nothing to read. NULL means "not recorded"; ABHA creation refuses
until it is set rather than guessing the legal text.
"""

import sqlalchemy as sa
from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facilities", sa.Column("ownership", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_facilities_ownership",
        "facilities",
        "ownership IS NULL OR ownership IN ('government', 'private')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_facilities_ownership", "facilities", type_="check")
    op.drop_column("facilities", "ownership")
