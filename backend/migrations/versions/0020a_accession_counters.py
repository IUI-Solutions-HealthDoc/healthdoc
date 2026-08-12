"""0020a_accession_counters

Revision ID: 0020a
Revises: 0020
Create Date: 2026-08-10

Builds: accession_counters — the allocator behind lab and radiology
accession numbers (LAB-<YYYYMMDD>-<SEQ5>, RAD-<YYYYMMDD>-<SEQ5>).

WHY "0020a" AND NOT 0035
------------------------
Same convention as 0003a: an out-of-band correction inserted directly after
the current head rather than consuming a number the §2 map has already
allocated to a module. 0021-0034 are spoken for; this belongs immediately
after 0020, and numbering it 0035 would either force it to wait for fourteen
unrelated migrations or leave the chain numerically out of order.

WHY A COUNTERS ROW AND NOT A SEQUENCE
-------------------------------------
§2.2 says non-financial identifiers use a Postgres sequence, and reserves
counters tables for gapless financial numbering. Accession numbers don't
need to be gapless — but their frozen format resets the sequence every day,
and a Postgres sequence cannot reset itself. The alternatives were a
sequence per day (365 objects a year per prefix, created by DDL in the
request path, which is exactly what UHID avoids) or dropping the daily
reset, which would be an ADR since §2.2 marks the format frozen.

So: one row per (prefix, date), allocated with
INSERT ... ON CONFLICT DO UPDATE ... RETURNING. That is atomic, and unlike
SELECT ... FOR UPDATE it also covers the first allocation of the day, when
there is no row to lock yet. Vani proved that pattern in billing's
_allocate_billing_number.

NOT facility-scoped: §3 defines accession_number as globally UNIQUE and its
format carries no facility segment, so the counter is global per day. If the
format ever gains a facility segment, this table needs facility_id and a
wider unique key.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020a"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accession_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("prefix", sa.String(10), nullable=False),
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("prefix", "counter_date",
                            name="uq_accession_counters_prefix_date"),
        sa.CheckConstraint("prefix IN ('LAB','RAD')",
                           name="ck_accession_counters_prefix"),
        sa.CheckConstraint("last_value >= 0",
                           name="ck_accession_counters_last_value_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("accession_counters")
