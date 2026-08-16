"""0041_visit_number_counters_and_idempotency_fix

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-14

Fixes two schema gaps found via the #243 (BB-W7-01) OPD/IPD integration
journey tests — both invisible to unit tests, only caught by an end-to-end
POST /visits call against a real migrated database.

A. visit_number_counters — table never created.
   app/opd/models.py's VisitNumberCounter model has carried its own TODO
   since it was written: "this table has no home in the §3 migration map
   yet ... Create a real migration for it." That never happened. Every
   git grep across migrations/versions/*.py for "visit_number_counters"
   returns zero matches (checked 0001 through 0034, current head) even
   though app/opd/visit_number.py depends on it for every POST /visits —
   i.e. every OPD/IPD registration, unconditionally.

B. idempotency_keys.updated_at — column missing when this migration was
   first written; made idempotent below (checks information_schema first)
   because a prior partial/manual attempt may have already added it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # A. visit_number_counters
    # ------------------------------------------------------------------
    has_table = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'visit_number_counters'"
    )).first()
    if has_table is None:
        op.create_table(
            "visit_number_counters",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("uuid_generate_v4()")),
            sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("facilities.id"), nullable=False),
            sa.Column("counter_date", sa.Date(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.UniqueConstraint(
                "facility_id", "counter_date",
                name="uq_visit_number_counters_facility_id_counter_date",
            ),
        )

    # ------------------------------------------------------------------
    # B. idempotency_keys.updated_at
    # ------------------------------------------------------------------
    has_column = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'idempotency_keys' AND column_name = 'updated_at'"
    )).first()
    if has_column is None:
        op.add_column(
            "idempotency_keys",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute("UPDATE idempotency_keys SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column(
            "idempotency_keys", "updated_at",
            nullable=False, server_default=sa.func.now(),
        )


def downgrade() -> None:
    op.execute("ALTER TABLE idempotency_keys DROP COLUMN IF EXISTS updated_at")
    op.execute("DROP TABLE IF EXISTS visit_number_counters")