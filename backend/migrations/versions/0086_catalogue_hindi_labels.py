"""Nullable Hindi labels for master catalogues.

Revision ID: 0086
Revises: 0085
Create Date: 2026-09-25

English `name` / `description` remain required. Hindi columns are optional;
the UI falls back to English when null or blank. Invoice line snapshots stay
English as stored — only live catalogue pickers use description_hi.
"""
from alembic import op
import sqlalchemy as sa

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A sandbox database that applied the original 0085 profile-kind migration
    # had varchar(10); the restored 0085 source specifies varchar(50).
    op.alter_column(
        "patients",
        "abha_profile_token_kind",
        existing_type=sa.String(10),
        type_=sa.String(50),
        existing_nullable=False,
        existing_server_default="abha",
    )
    op.add_column("facilities", sa.Column("name_hi", sa.Text(), nullable=True))
    op.add_column("departments", sa.Column("name_hi", sa.Text(), nullable=True))
    op.add_column("wards", sa.Column("name_hi", sa.Text(), nullable=True))
    op.add_column(
        "charge_master",
        sa.Column("description_hi", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("charge_master", "description_hi")
    op.drop_column("wards", "name_hi")
    op.drop_column("departments", "name_hi")
    op.drop_column("facilities", "name_hi")
