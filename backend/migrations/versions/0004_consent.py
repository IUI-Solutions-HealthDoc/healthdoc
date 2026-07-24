"""consent — consent_purposes, consent_records, consent_withdrawals,
data_access_log, consent_renewal_reminders

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-22

Owner: B7 (B7-W1-02). Schema doc: HealthDoc_Database_Schema_v3_4 §3 "0004 — consent".

Notes for reviewers (flag these interpretations in the PR, per repo convention
of calling out ambiguous doc text rather than silently guessing):

1. Enum/status columns are varchar(50), not the varchar(30) shown inline in
   the schema doc's §3 table listing — same override migration 0003 already
   applied to audit_log_archive.verification_status, per the v3.3 changelog
   entry "enum width rule -> varchar(50)".

2. granted_by_type, channel, access_channel have no explicit NULL/NOT NULL
   marker in the doc (unlike patient_id, purpose_id, granted_by_user_id,
   which ARE marked). Treated as NOT NULL here since they're the essential
   classification fields for the row — flag for Tech Lead confirmation.

3. patient_id / visit_id / department_id-style deferred FKs: patients table
   doesn't exist until migration 0006, visits until 0007. Those columns are
   plain UUID here, exactly like audit_logs.patient_id in migration 0003 —
   real FK gets added later via ALTER TABLE in those migrations.

4. consent_withdrawals.withdrawn_by_type includes 'system_expiry', which is
   NOT one of the values in enums.py GrantedByType (patient/guardian/nominee
   only). Since there's no matching CheckedEnum, this uses a literal CHECK
   list instead of EnumClass.sql_check() — same pattern migration 0003 used
   for verification_status, which also has no enums.py counterpart.

5. data_access_log is append-only + monthly-partitioned by accessed_at,
   exactly like audit_logs — same block-update/delete trigger pattern, same
   BRIN index per the "Index strategy addendum" (§3-end): BRIN on
   accessed_at inside access-log partitions for near-zero write cost.
   Unlike audit_logs, it has NO hash chain / signature columns — the schema
   doc doesn't list any for this table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. consent_purposes — plain lookup table, ordinary Alembic ops.
    # ------------------------------------------------------------------
    op.create_table(
        "consent_purposes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("purpose_code", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_expiry_days", sa.Integer(), nullable=True),
        sa.Column("requires_explicit_consent", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("purpose_code", name="uq_consent_purposes_purpose_code"),
    )

    # ------------------------------------------------------------------
    # 2. consent_records — [Blame]: created_by/updated_by point at users.
    #    Immutable after insert except status + status_changed_at (enforced
    #    at the app/service layer — Postgres doesn't have per-column
    #    immutability triggers here, unlike audit_logs' full append-only
    #    lock, because status DOES need to change on withdrawal/expiry).
    # ------------------------------------------------------------------
    op.create_table(
        "consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),  # FK added in 0006
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=True),     # FK added in 0007
        sa.Column(
            "purpose_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_purposes.id", ondelete="RESTRICT", name="fk_consent_records_purpose_id"),
            nullable=False,
        ),
        sa.Column("granted_by_type", sa.String(50), nullable=False),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_records_granted_by_user_id"),
            nullable=True,
        ),
        sa.Column("guardian_name", sa.Text(), nullable=True),
        sa.Column("guardian_relationship", sa.String(50), nullable=True),
        sa.Column("guardian_id_proof_file_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK added in 0019
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),  # NULLABLE per issue spec
        sa.Column("scope", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("consent_artefact_id", sa.Text(), nullable=True),
        sa.Column("consent_artefact_signature", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="granted"),  # ConsentStatus enum
        sa.Column("status_changed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_records_created_by"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_records_updated_by"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "granted_by_type IN ('patient', 'guardian', 'nominee')",
            name="ck_consent_records_granted_by_type",
        ),
        sa.CheckConstraint(
            "channel IN ('verbal', 'written', 'digital_otp', 'abdm_consent_manager')",
            name="ck_consent_records_channel",
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'granted', 'denied', 'revoked', 'expired')",
            name="ck_consent_records_status",
        ),
    )
    op.create_index("ix_consent_records_patient_id", "consent_records", ["patient_id"])
    op.create_index("ix_consent_records_purpose_id", "consent_records", ["purpose_id"])

    # ------------------------------------------------------------------
    # 3. consent_withdrawals — append-only; a new row here flips the
    #    parent consent_records.status to 'revoked' (app-layer, same
    #    transaction — repo rule from the audit module docstring applies
    #    equally well here: write + status flip in one commit).
    # ------------------------------------------------------------------
    op.create_table(
        "consent_withdrawals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "consent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_records.id", ondelete="RESTRICT", name="fk_consent_withdrawals_consent_id"),
            nullable=False,
        ),
        sa.Column("withdrawn_by_type", sa.String(50), nullable=False),
        sa.Column(
            "withdrawn_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_consent_withdrawals_withdrawn_by_user_id"),
            nullable=True,
        ),
        sa.Column("withdrawn_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("cascaded_actions", postgresql.JSONB(), nullable=True),
        sa.Column("cascade_deadline", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cascade_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        # No CheckedEnum in enums.py covers 'system_expiry' — literal CHECK,
        # same pattern migration 0003 used for verification_status.
        sa.CheckConstraint(
            "withdrawn_by_type IN ('patient', 'guardian', 'nominee', 'system_expiry')",
            name="ck_consent_withdrawals_withdrawn_by_type",
        ),
    )
    op.create_index("ix_consent_withdrawals_consent_id", "consent_withdrawals", ["consent_id"])

    # ------------------------------------------------------------------
    # 4. data_access_log — partitioned parent, append-only, hash-free.
    #    Raw SQL for the same reason audit_logs is raw SQL: Alembic
    #    autogenerate can't emit PARTITION BY RANGE or trigger DDL.
    #    Constraint names given explicitly to match Base's NAMING_CONVENTION,
    #    since raw SQL doesn't pick that up automatically.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE data_access_log (
            id                UUID        NOT NULL DEFAULT uuid_generate_v4(),
            consent_id        UUID        NULL
                              CONSTRAINT fk_data_access_log_consent_id REFERENCES consent_records(id) ON DELETE RESTRICT,
            user_id           UUID        NOT NULL
                              CONSTRAINT fk_data_access_log_user_id REFERENCES users(id) ON DELETE RESTRICT,
            role              TEXT,
            resource_type     TEXT,
            resource_id       UUID,
            patient_id        UUID        NULL,
            purpose_code      VARCHAR(50),
            access_channel    VARCHAR(50) NOT NULL
                              CONSTRAINT ck_data_access_log_access_channel
                              CHECK (access_channel IN ('ui', 'api', 'abdm_hiu', 'export')),
            emergency_access  BOOLEAN     NOT NULL DEFAULT false,  -- break-glass flag
            consent_required  BOOLEAN,
            consent_verified  BOOLEAN,
            accessed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_data_access_log PRIMARY KEY (id, accessed_at)
        ) PARTITION BY RANGE (accessed_at);
        """
    )

    op.execute("CREATE INDEX ix_data_access_log_user_id ON data_access_log (user_id, accessed_at);")
    op.execute("CREATE INDEX ix_data_access_log_patient_id ON data_access_log (patient_id, accessed_at);")
    # Index strategy addendum (§3-end): BRIN on accessed_at inside
    # audit/access-log partitions — same reasoning as audit_logs in 0003.
    op.execute("CREATE INDEX ix_data_access_log_accessed_at_brin ON data_access_log USING BRIN (accessed_at);")

    # Monthly partitions: current month + 5 ahead, same rolling-forward
    # TODO as audit_logs — needs a scheduled job to keep creating partitions.
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
                part_name  := 'data_access_log_' || to_char(part_start, 'YYYY_MM');
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF data_access_log FOR VALUES FROM (%L) TO (%L);',
                    part_name, part_start, part_end
                );
            END LOOP;
        END $$;
        """
    )

    # Append-only enforcement: block UPDATE and DELETE, same as audit_logs.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_data_access_log_block_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'data_access_log is append-only: % not permitted on this table', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_data_access_log_block_update
        BEFORE UPDATE OR DELETE ON data_access_log
        FOR EACH ROW EXECUTE FUNCTION trg_data_access_log_block_update();
        """
    )

    # ------------------------------------------------------------------
    # 5. consent_renewal_reminders — plain table, ordinary Alembic ops.
    # ------------------------------------------------------------------
    op.create_table(
        "consent_renewal_reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "consent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_records.id", ondelete="RESTRICT", name="fk_consent_renewal_reminders_consent_id"),
            nullable=False,
        ),
        sa.Column("remind_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notification_channel", sa.String(30), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_consent_renewal_reminders_consent_id", "consent_renewal_reminders", ["consent_id"])
    op.create_index("ix_consent_renewal_reminders_remind_at", "consent_renewal_reminders", ["remind_at"])


def downgrade() -> None:
    op.drop_index("ix_consent_renewal_reminders_remind_at", table_name="consent_renewal_reminders")
    op.drop_index("ix_consent_renewal_reminders_consent_id", table_name="consent_renewal_reminders")
    op.drop_table("consent_renewal_reminders")

    op.execute("DROP TRIGGER IF EXISTS trg_data_access_log_block_update ON data_access_log;")
    op.execute("DROP FUNCTION IF EXISTS trg_data_access_log_block_update();")
    op.execute("DROP TABLE IF EXISTS data_access_log CASCADE;")

    op.drop_index("ix_consent_withdrawals_consent_id", table_name="consent_withdrawals")
    op.drop_table("consent_withdrawals")

    op.drop_index("ix_consent_records_purpose_id", table_name="consent_records")
    op.drop_index("ix_consent_records_patient_id", table_name="consent_records")
    op.drop_table("consent_records")

    op.drop_table("consent_purposes")
