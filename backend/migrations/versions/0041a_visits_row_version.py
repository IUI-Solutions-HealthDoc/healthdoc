"""0041a_visits_row_version

Revision ID: 0041a
Revises: 0041
Create Date: 2026-08-14

Fixes a third schema gap found via the #243 (BB-W7-01) OPD integration
journey test — landing right after 0035 as an out-of-band correction,
same convention as 0003a/0020a, since this was found and fixed in the
same working session as 0035 and hasn't been shared/merged yet.

app/opd/models.py's Visit model declares row_version (Mapped[int],
NOT NULL, server_default="1") for optimistic concurrency per §4A.2 — its
own docstring says so explicitly: "Visit gains row_version (§4A.2 --
required on every mutable clinical/financial row; was only on Encounter
before)." Encounter got row_version via migration 0021. Visit's model
was updated to match, but no migration ever added the column to the
real visits table — confirmed via a live INSERT failing with
UndefinedColumnError: column visits.row_version does not exist.

This blocks every POST /visits (registration), since the ORM's RETURNING
clause always includes every mapped column.
"""
from alembic import op
import sqlalchemy as sa

revision = "0041a"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    has_column = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'visits' AND column_name = 'row_version'"
    )).first()
    if has_column is None:
        op.add_column(
            "visits",
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    op.execute("ALTER TABLE visits DROP COLUMN IF EXISTS row_version")