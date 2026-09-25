"""Record which ABHA login family issued the stored profile X-token.

Revision ID: 0085
Revises: 0084
Create Date: 2026-09-25

An ABHA-number/Aadhaar/mobile login and an ABHA-address (PHR) login each
return a profile X-token, but each token only opens its own endpoint family
(/v3/profile/account vs /v3/phr/web/login/profile). Without the kind, a PHR
token would be sent to the ABHA-number card endpoint and refused.

Existing tokens were all issued by the ABHA-number family, so the server
default 'abha' is their true value, not a placeholder.

Reconstruction note: a first 0085 with this column at varchar(10) was applied
to one local database on 2026-09-24 and its source was lost before commit.
This file restores the same column, default and constraint name at the
schema-rule width, varchar(50).
"""
from alembic import op
import sqlalchemy as sa

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "abha_profile_token_kind",
            sa.String(50),
            nullable=False,
            server_default="abha",
        ),
    )
    # Short name: the naming convention prefixes it to
    # ck_patients_abha_profile_token_kind.
    op.create_check_constraint(
        "abha_profile_token_kind",
        "patients",
        "abha_profile_token_kind IN ('abha', 'phr')",
    )


def downgrade() -> None:
    op.drop_constraint("abha_profile_token_kind", "patients", type_="check")
    op.drop_column("patients", "abha_profile_token_kind")
