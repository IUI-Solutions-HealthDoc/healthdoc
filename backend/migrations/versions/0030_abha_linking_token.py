"""Migration 0030 — ABHA linking token, encrypted storage on patients (B1-W3-02).

ABDM returns a linking token when an ABHA is linked to a care context. It is
sensitive: stored AES-256-GCM encrypted (never plaintext), key-versioned for rotation,
same handling as Aadhaar (common/security.py). Coordinates with B2's patients table
(0006) — this ALTER runs after it. Renumber down_revision if the plan shifts.
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("abha_linking_token_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("patients", sa.Column("abha_linking_key_version", sa.SmallInteger(), nullable=True))
    op.add_column("patients", sa.Column("abha_linked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_patients_abha_token_key_version",
        "patients",
        "(abha_linking_token_encrypted IS NULL) = (abha_linking_key_version IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_patients_abha_token_key_version", "patients", type_="check")
    op.drop_column("patients", "abha_linked_at")
    op.drop_column("patients", "abha_linking_key_version")
    op.drop_column("patients", "abha_linking_token_encrypted")
