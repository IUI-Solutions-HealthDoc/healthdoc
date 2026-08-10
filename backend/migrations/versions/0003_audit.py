"""audit — audit_logs (append-only, hash-chained, monthly-partitioned),
audit_counters, audit_log_archive, audit_integrity_checks

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. audit_logs — partitioned parent table.
    #    Raw SQL because Alembic autogenerate can't produce
    #    `PARTITION BY RANGE` or trigger DDL (schema doc confirms this).
    #    Requires uuid-ossp + pgcrypto extensions from migration 0001,
    #    and facilities / users from migration 0002.
    #
    #    Constraint names (pk_audit_logs, fk_audit_logs_*) are given
    #    explicitly to match app.common.db.Base's NAMING_CONVENTION —
    #    this table's DDL is raw SQL, so it doesn't get that convention
    #    applied automatically the way ORM-managed tables do.
    #
    #    v3.4.1 policy: no table may FK to audit_logs.id — reference
    #    audit rows by value only. Nothing to change here; this is a
    #    constraint on other modules, not this migration.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit_logs (
            id              UUID        NOT NULL DEFAULT uuid_generate_v4(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            facility_id     UUID        NOT NULL
                            CONSTRAINT fk_audit_logs_facility_id REFERENCES facilities(id) ON DELETE RESTRICT,
            user_id         UUID        NULL
                            CONSTRAINT fk_audit_logs_user_id REFERENCES users(id) ON DELETE RESTRICT,
            role            TEXT,
            department_id   UUID        NULL,
            action          TEXT        NOT NULL,
            resource_type   TEXT        NOT NULL,
            resource_id     UUID,
            patient_id      UUID        NULL,
            visit_id        UUID        NULL,
            old_value       JSONB,
            new_value       JSONB,
            reason          TEXT,
            ip_address      INET,
            device_id       TEXT,
            -- Per-facility monotonic write order, gaplessly assigned by
            -- trg_audit_logs_assign_chain_seq below from the
            -- audit_counters table (never a raw Postgres SEQUENCE --
            -- see the trigger's comment for why gaplessness matters
            -- here specifically). This is what the async sealer walks
            -- in order to build the hash chain.
            chain_seq       BIGINT      NOT NULL,
            -- prev_hash/entry_hash/signature/signer_key_id are all NULL
            -- at insert time now. A single-threaded per-facility sealer
            -- job (separate, not part of this migration) fills them in
            -- afterwards, walking rows in chain_seq order. sealed_at
            -- NULL means "not yet chained"; sealed_at older than the
            -- 15-minute SLA is an alert (sealer down), not a data error.
            prev_hash       CHAR(64)    NULL,
            entry_hash      CHAR(64)    NULL,
            signature       TEXT        NULL,
            signer_key_id   TEXT        NULL,
            sealed_at       TIMESTAMPTZ NULL,
            CONSTRAINT pk_audit_logs PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )

    # Uniqueness of the per-facility write sequence. Postgres requires a
    # unique constraint on a partitioned table to include the partition
    # key (created_at) -- schema doc §3 0003 states the logical
    # constraint as UNIQUE (facility_id, chain_seq); created_at is
    # appended here only to satisfy that Postgres requirement, it adds
    # no looseness in practice since chain_seq is already monotonic.
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT uq_audit_logs_facility_chain_seq "
        "UNIQUE (facility_id, chain_seq, created_at);"
    )

    # Indexes on the parent — every partition inherits them automatically
    # (Postgres 11+). Named exactly as the schema doc specifies.
    op.execute("CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id, created_at);")
    op.execute("CREATE INDEX ix_audit_logs_patient_id ON audit_logs (patient_id, created_at);")
    op.execute("CREATE INDEX ix_audit_logs_resource ON audit_logs (resource_type, resource_id);")

    # v3.3 — §3 "Index strategy addendum": BRIN on created_at inside
    # audit/access-log partitions. Near-zero write overhead; speeds up
    # range scans *within* a partition (partition pruning already handles
    # month-level granularity; BRIN handles ranges inside a single
    # month's partition). Deliberately NOT adding GIN on old_value/
    # new_value — the doc explicitly says not to, since this table is
    # write-heavy and already covered by the indexed columns above.
    op.execute("CREATE INDEX ix_audit_logs_created_at_brin ON audit_logs USING BRIN (created_at);")

    # ------------------------------------------------------------------
    # 2. Monthly partitions. Creates the current month + 5 ahead so the
    #    team doesn't hit "no partition for this row" on day one.
    #    TODO (flag this in your PR): partitions need to keep rolling
    #    forward — either a scheduled job that runs monthly, or a small
    #    cron-triggered migration. Not solving that here, just noting it
    #    so it doesn't get forgotten.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        DECLARE
            start_month date := date_trunc('month', now())::date;
            i int;
            part_start date;
            part_end date;
            part_name text;
        BEGIN
            FOR i IN 0..5 LOOP
                part_start := (start_month + (i || ' months')::interval)::date;
                part_end   := (start_month + ((i + 1) || ' months')::interval)::date;
                part_name  := 'audit_logs_' || to_char(part_start, 'YYYY_MM');
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF audit_logs FOR VALUES FROM (%L) TO (%L);',
                    part_name, part_start, part_end
                );
            END LOOP;
        END $$;
        """
    )

    # DEFAULT partition -- mandatory, not optional (schema doc §3 0003).
    # Without this, the first INSERT after the last provisioned month's
    # range fails outright -- and because the audit write shares the
    # mutation's own transaction, that takes every write in the hospital
    # down with it at 00:00 on day one of the following month. Rows that
    # land here are an alert for ops, not a failure for the user.
    # TODO(follow-up issue): a scheduled job (pg_partman or a
    # cron-triggered migration/function) must keep >=3 months of real
    # partitions provisioned ahead of `now()` so DEFAULT stays empty in
    # steady state -- not implemented in this migration, flagging per
    # review comment #3.
    op.execute("CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT;")

    # ------------------------------------------------------------------
    # 3. Append-only enforcement: block UPDATE and DELETE outright.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_audit_logs_block_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: % not permitted on this table', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_block_update
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION trg_audit_logs_block_update();
        """
    )

    # ------------------------------------------------------------------
    # 4. audit_counters — the gapless per-facility chain_seq allocator.
    #    Same pattern as billing_counters: one row per facility,
    #    incremented with a locking UPDATE inside the SAME transaction
    #    as the audit insert, so a rollback undoes the increment too.
    #
    #    Why not a Postgres SEQUENCE (previous version of this
    #    migration): sequences are NOT transactional -- a rolled-back
    #    insert still permanently consumes its nextval(). In normal
    #    operation that produces chain_seq values like 1, 2, 4, 5, and
    #    the sealer then cannot tell "transaction 3 rolled back"
    #    (harmless, constant) apart from "someone deleted row 3" (the
    #    exact tampering the chain exists to catch) -- the two are
    #    indistinguishable from gaps alone. A counter row that only
    #    advances on commit has no such gaps: any gap the sealer finds
    #    is unambiguous evidence of tampering.
    #
    #    Created here as an ordinary table (not partitioned -- one row
    #    per facility, not one row per audit event). No FK from
    #    facilities to here; a row is upserted on first audit write for
    #    a facility inside the trigger below (see its comment for why),
    #    so this table doesn't need facilities-module code to seed it.
    # ------------------------------------------------------------------
    op.create_table(
        "audit_counters",
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_counters_facility_id"),
            primary_key=True,
        ),
        sa.Column("last_value", sa.BigInteger(), nullable=False, server_default="0"),
    )

    # ------------------------------------------------------------------
    # 5. Chain sequencing only -- NOT the hash chain itself anymore.
    #
    #    Per review: computing entry_hash inline (old approach) reads
    #    the previous row's hash with a plain SELECT, so two concurrent
    #    INSERTs can read the same last_hash and silently fork the
    #    chain -- a lost-update race, not just a performance problem.
    #    The only way to make an inline chain race-free is to serialise
    #    every audit write hospital-wide, which serialises every
    #    mutation. Facilities also write offline and sync later, so one
    #    global chain is impossible by construction.
    #
    #    So this trigger does only ONE thing: assign chain_seq from
    #    audit_counters (above), gaplessly. The INSERT..ON CONFLICT
    #    upsert followed by an UPDATE..RETURNING is one atomic path:
    #    the UPDATE takes a row lock on this facility's counter row for
    #    the rest of the transaction, so concurrent inserts for the
    #    SAME facility serialise on that one row (not on all of
    #    audit_logs), and a rollback releases the lock without having
    #    consumed a number -- gapless by construction, no DDL on the
    #    write path, no sequence-name string-building. The row is
    #    written with prev_hash/entry_hash/signature/signer_key_id all
    #    NULL and sealed_at NULL.
    #
    #    A separate, single-threaded per-facility sealer job (not part
    #    of this migration -- tracked as its own follow-up, opened by
    #    Tech Lead as a blocking issue since it's what makes the table
    #    tamper-evident in production) walks unsealed rows in chain_seq
    #    order and fills prev_hash/entry_hash/signature. Sealing is
    #    idempotent/restartable, and the cloud verifies each facility's
    #    chain independently without ever re-chaining on ingest. A gap
    #    in chain_seq found by the sealer/verifier is now unambiguous:
    #    it can only mean a row was removed.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_audit_logs_assign_chain_seq() RETURNS trigger AS $$
        DECLARE
            next_seq bigint;
        BEGIN
            INSERT INTO audit_counters (facility_id, last_value)
            VALUES (NEW.facility_id, 0)
            ON CONFLICT (facility_id) DO NOTHING;

            UPDATE audit_counters
            SET last_value = last_value + 1
            WHERE facility_id = NEW.facility_id
            RETURNING last_value INTO next_seq;

            NEW.chain_seq := next_seq;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_assign_chain_seq
        BEFORE INSERT ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION trg_audit_logs_assign_chain_seq();
        """
    )

    # ------------------------------------------------------------------
    # 6. audit_log_archive — ordinary table, normal Alembic ops.
    #    See models.py docstring for the nullability reasoning: only
    #    facility_id + partition_name are required at creation time.
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_log_archive_facility_id"),
            nullable=False,
        ),
        sa.Column("partition_name", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("object_storage_bucket", sa.Text(), nullable=True),
        sa.Column("object_storage_key", sa.Text(), nullable=True),
        sa.Column("archive_file_hash", sa.CHAR(64), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # v3.4.1: enum/status columns are varchar(50) — overrides the
        # narrower varchar(30) shown inline in the schema doc for this
        # column specifically.
        sa.Column("verification_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'failed')",
            name="ck_audit_log_archive_verification_status",
        ),
    )
    op.create_index("ix_audit_log_archive_facility_id", "audit_log_archive", ["facility_id"])

    # ------------------------------------------------------------------
    # 7. audit_integrity_checks — ordinary table.
    # ------------------------------------------------------------------
    op.create_table(
        "audit_integrity_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT", name="fk_audit_integrity_checks_facility_id"),
            nullable=False,
        ),
        sa.Column("partition_name", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("rows_checked", sa.BigInteger(), nullable=False),
        sa.Column("chain_valid", sa.Boolean(), nullable=False),
        sa.Column("signatures_valid", sa.BigInteger(), nullable=False),
        sa.Column("signatures_invalid", sa.BigInteger(), nullable=False),
        sa.Column("first_mismatch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alerted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_integrity_checks_facility_id", "audit_integrity_checks", ["facility_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_integrity_checks_facility_id", table_name="audit_integrity_checks")
    op.drop_table("audit_integrity_checks")

    op.drop_index("ix_audit_log_archive_facility_id", table_name="audit_log_archive")
    op.drop_table("audit_log_archive")

    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_assign_chain_seq ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS trg_audit_logs_assign_chain_seq();")
    op.drop_table("audit_counters")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_block_update ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS trg_audit_logs_block_update();")
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE;")
