"""Store enrolment/profile X-tokens apart from HIP linking tokens.

Revision ID: 0083
Revises: 0082
Create Date: 2026-09-21

M1 enrolment and login return an X-token for profile/card access. That
credential was being written to patients.abha_linking_token_encrypted, which
is the HIP linking column. The two are not interchangeable. New writes go
here; linking tokens stay null until a genuine M2 link token exists.
"""
from alembic import op
import sqlalchemy as sa

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("abha_profile_token_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("patients", sa.Column("abha_profile_token_key_version", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_patients_abha_profile_token_key_version",
        "patients",
        "(abha_profile_token_encrypted IS NULL) = (abha_profile_token_key_version IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_patients_abha_profile_token_key_version", "patients", type_="check")
    op.drop_column("patients", "abha_profile_token_key_version")
    op.drop_column("patients", "abha_profile_token_encrypted")
