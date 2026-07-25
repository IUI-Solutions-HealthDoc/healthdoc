"""audit — audit_logs (append-only, hash-chained, monthly-partitioned),
audit_log_archive, audit_integrity_checks

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
            prev_hash       CHAR(64),
            entry_hash      CHAR(64)    NOT NULL,
            signature       TEXT        NOT NULL,
            signer_key_id   TEXT        NOT NULL,
            CONSTRAINT pk_audit_logs PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
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
    # 4. Hash chain: BEFORE INSERT, pull the previous row's entry_hash
    #    and compute entry_hash = sha256(prev_hash || payload) using
    #    pgcrypto's digest() (enabled in migration 0001).
    #
    #    Known limitation, flag it in your PR for Tech Lead visibility:
    #    "SELECT ... ORDER BY created_at DESC LIMIT 1" scans across
    #    partitions to find the latest row. Fine at pilot/dev volume. If
    #    it becomes a bottleneck, replace with a small single-row
    #    `audit_chain_state(last_hash)` table that the trigger
    #    reads/updates instead — same hash chain, O(1) lookup.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_audit_logs_compute_hash() RETURNS trigger AS $$
        DECLARE
            last_hash char(64);
            payload text;
        BEGIN
            SELECT entry_hash INTO last_hash
            FROM audit_logs
            ORDER BY created_at DESC, id DESC
            LIMIT 1;

            NEW.prev_hash := COALESCE(last_hash, repeat('0', 64));

            payload := concat_ws('|',
                NEW.id, NEW.created_at, NEW.facility_id, NEW.user_id,
                NEW.action, NEW.resource_type, NEW.resource_id,
                NEW.patient_id, NEW.visit_id,
                COALESCE(NEW.old_value::text, ''),
                COALESCE(NEW.new_value::text, '')
            );

            NEW.entry_hash := encode(digest(NEW.prev_hash || payload, 'sha256'), 'hex');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_compute_hash
        BEFORE INSERT ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION trg_audit_logs_compute_hash();
        """
    )

    # ------------------------------------------------------------------
    # 5. audit_log_archive — ordinary table, normal Alembic ops.
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
    # 6. audit_integrity_checks — ordinary table.
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

    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_compute_hash ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS trg_audit_logs_compute_hash();")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_block_update ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS trg_audit_logs_block_update();")
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE;")
