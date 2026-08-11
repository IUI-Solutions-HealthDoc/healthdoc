"""consent — consent_purposes, consent_records, consent_withdrawals,
break_glass_grants, data_access_log, consent_renewal_reminders

Revision ID: 0004
Revises: 0003a

Notes for reviewers:

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
   real FK gets added later via ALTER TABLE in those migrations. This now
   also applies to break_glass_grants.patient_id (new table, same rule).

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

6. break_glass_grants.justification's "≥20 chars, mandatory" is enforced as
   both a DB CHECK (char_length) and a service-layer check — the doc doesn't
   say explicitly which layer owns it, but a bypassable justification gate
   on emergency PHI access is worth the redundancy. Flag for confirmation.

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003a"
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
    #    Immutable after insert except status / status_changed_at.
    #
    #    v3.13 update: this is now a DB trigger, not app-layer-only,
    #    following the invoices (0014) trg_invoices_freeze precedent —
    #    same shape of problem (a row that's frozen except for a small
    #    mutable set of columns needed for a status lifecycle). The
    #    schema doc doesn't spell out a trigger for consent_records the
    #    way it does for audit_logs' full append-only block, but the
    #    invoices pattern is the closest match in this codebase and Tech
    #    Lead flagged app-layer-only as insufficient for this exact
    #    "frozen except N columns" shape. updated_at/updated_by are also
    #    left mutable (same reasoning as invoices: they track the status
    #    change itself, not a separate edit).
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
    op.create_index("ix_consent_records_granted_by_user_id", "consent_records", ["granted_by_user_id"])
    op.create_index("ix_consent_records_created_by", "consent_records", ["created_by"])
    op.create_index("ix_consent_records_updated_by", "consent_records", ["updated_by"])

    # trg_consent_records_freeze: blocks changes to any column other than
    # status / status_changed_at / updated_at / updated_by. Mirrors
    # trg_invoices_freeze's "compare OLD vs NEW on the frozen set" shape
    # rather than blanket-blocking UPDATE the way audit_logs/data_access_log
    # do, since those two columns legitimately change on withdrawal/expiry.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_consent_records_freeze() RETURNS trigger AS $$
        BEGIN
            IF NEW.id                          IS DISTINCT FROM OLD.id
               OR NEW.patient_id                IS DISTINCT FROM OLD.patient_id
               OR NEW.visit_id                   IS DISTINCT FROM OLD.visit_id
               OR NEW.purpose_id                 IS DISTINCT FROM OLD.purpose_id
               OR NEW.granted_by_type            IS DISTINCT FROM OLD.granted_by_type
               OR NEW.granted_by_user_id         IS DISTINCT FROM OLD.granted_by_user_id
               OR NEW.guardian_name              IS DISTINCT FROM OLD.guardian_name
               OR NEW.guardian_relationship      IS DISTINCT FROM OLD.guardian_relationship
               OR NEW.guardian_id_proof_file_id  IS DISTINCT FROM OLD.guardian_id_proof_file_id
               OR NEW.granted_at                 IS DISTINCT FROM OLD.granted_at
               OR NEW.expires_at                 IS DISTINCT FROM OLD.expires_at
               OR NEW.scope                      IS DISTINCT FROM OLD.scope
               OR NEW.channel                    IS DISTINCT FROM OLD.channel
               OR NEW.consent_artefact_id        IS DISTINCT FROM OLD.consent_artefact_id
               OR NEW.consent_artefact_signature IS DISTINCT FROM OLD.consent_artefact_signature
               OR NEW.created_by                 IS DISTINCT FROM OLD.created_by
               OR NEW.created_at                 IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'consent_records is immutable except status/status_changed_at (row %)', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_consent_records_freeze
        BEFORE UPDATE ON consent_records
        FOR EACH ROW EXECUTE FUNCTION trg_consent_records_freeze();
        """
    )
    # ------------------------------------------------------------------
    # 3. consent_withdrawals — append-only; inserting a row flips the
    #    parent consent_records.status to 'revoked' via a trigger
    #    (v3.13 update — was app-layer-only; moved to a DB trigger for
    #    the same reason as trg_consent_records_freeze above, so the
    #    invariant holds regardless of which code path inserts the row).
    #    status_changed_at is set inside the same trigger so the two
    #    stay consistent by construction.
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
    op.create_index(
        "ix_consent_withdrawals_withdrawn_by_user_id", "consent_withdrawals", ["withdrawn_by_user_id"]
    )

    # AFTER INSERT trigger: a new consent_withdrawals row flips its parent
    # consent_records.status to 'revoked' and stamps status_changed_at.
    # Runs as a second statement inside whatever transaction did the
    # INSERT, so it shares that transaction's atomicity — no separate
    # commit, no risk of the withdrawal existing without the flip (or
    # vice versa). trg_consent_records_freeze (above) explicitly allows
    # status/status_changed_at to change, so this UPDATE is not blocked
    # by that trigger.
    # v3.13 fix (Tech Lead review, re-applied here after this migration
    # was regenerated -- do not simplify back to unconditional 'revoked'):
    # a system_expiry withdrawal must flip status to 'expired', not
    # 'revoked' -- those are different DPDP facts (the patient withdrew
    # it vs. it lapsed on its own), and an unconditional 'revoked' makes
    # ConsentStatus.EXPIRED unreachable from any code path. Also guards
    # against rewriting a consent that's already in a terminal state
    # (revoked/denied/expired) -- a withdrawal against a settled consent
    # is a duplicate insert or an upstream logic error and must fail
    # loudly rather than silently overwrite status_changed_at.
    #
    # PR #266 review: the terminal-status guard had a race -- two
    # concurrent withdrawals against the same consent could both SELECT
    # 'granted', both pass the guard, and both UPDATE, leaving two
    # consent_withdrawals rows for one consent (the exact duplicate this
    # guard exists to prevent). Postgres serialises the two UPDATEs but
    # not the two SELECTs, so the guard alone doesn't close the window --
    # FOR UPDATE locks the consent_records row on read, making the second
    # concurrent transaction wait, then re-read the now-terminal status
    # and raise as intended.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_consent_withdrawals_flip_status() RETURNS trigger AS $$
        DECLARE
            current_status text;
            new_status text;
        BEGIN
            SELECT status INTO current_status
              FROM consent_records
             WHERE id = NEW.consent_id
               FOR UPDATE;

            IF current_status IS NULL THEN
                RAISE EXCEPTION 'consent_withdrawals: no consent_records row %', NEW.consent_id;
            END IF;

            IF current_status IN ('revoked', 'denied', 'expired') THEN
                RAISE EXCEPTION
                    'consent_records % is already in terminal status % -- cannot withdraw again',
                    NEW.consent_id, current_status;
            END IF;

            new_status := CASE WHEN NEW.withdrawn_by_type = 'system_expiry'
                                THEN 'expired' ELSE 'revoked' END;

            UPDATE consent_records
            SET status = new_status,
                status_changed_at = NEW.withdrawn_at
            WHERE id = NEW.consent_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_consent_withdrawals_flip_status
        AFTER INSERT ON consent_withdrawals
        FOR EACH ROW EXECUTE FUNCTION trg_consent_withdrawals_flip_status();
        """
    )

    # ------------------------------------------------------------------
    # 3b. break_glass_grants — the emergency-access window. Added to the
    #     schema doc in v3.9 (after this migration's original v3.4
    #     baseline), under migration 0004 — this module's own table, not
    #     previously built. A grant is active iff
    #     now() < expires_at AND revoked_at IS NULL — checked at the
    #     service layer on read, not enforceable as a static CHECK.
    #     Every read under an active grant still writes data_access_log
    #     with emergency_access=true (see app/consent/access_log.py).
    #
    #     justification's >=20-char rule is enforced here as a DB CHECK
    #     (char_length) in addition to service-layer validation — the
    #     doc phrases it as "≥20 chars, mandatory" without saying
    #     explicitly whether it's DB- or app-enforced; given how easy a
    #     one-line CHECK is and how bad a bypassed break-glass
    #     justification would be, this errs on the stricter side. Flag
    #     for Tech Lead confirmation like the other ambiguous-text notes
    #     above.
    # ------------------------------------------------------------------
    op.create_table(
        "break_glass_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),  # FK added in 0006
        sa.Column(
            "granted_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_granted_to_user_id"),
            nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "revoked_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_revoked_by"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_break_glass_grants_reviewed_by"),
            nullable=True,
        ),
        sa.Column("review_outcome", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "char_length(justification) >= 20",
            name="ck_break_glass_grants_justification_length",
        ),
    )
    op.create_index(
        "ix_break_glass_grants_patient_id", "break_glass_grants", ["patient_id", "expires_at"]
    )
    op.create_index(
        "ix_break_glass_grants_granted_to_user_id",
        "break_glass_grants",
        ["granted_to_user_id", "expires_at"],
    )
    op.create_index("ix_break_glass_grants_revoked_by", "break_glass_grants", ["revoked_by"])
    op.create_index("ix_break_glass_grants_reviewed_by", "break_glass_grants", ["reviewed_by"])

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
    op.execute("CREATE INDEX ix_data_access_log_consent_id ON data_access_log (consent_id);")

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

    # DEFAULT partition -- the never-fail safety net. Six months of
    # monthly partitions eventually run out; without this, a row outside
    # that range fails the INSERT with "no partition found" rather than
    # landing somewhere. That matters more here than for audit_logs:
    # access_log.py writes on its own session inside try/except Exception,
    # so a range-exhaustion failure would otherwise be silently swallowed
    # -- the read succeeds, the log row never lands anywhere, and nobody
    # notices until an audit asks for records that don't exist. Rows
    # landing in DEFAULT are a monitoring signal (follow-up, not this
    # migration), not a failure.
    op.execute("CREATE TABLE data_access_log_default PARTITION OF data_access_log DEFAULT;")

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
    # consent_renewal_reminders — plain table, ordinary Alembic ops.
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
        sa.Column("notification_channel", sa.String(50), nullable=True),  # blanket enum-width rule -> 50
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
    # data_access_log_default and the monthly partitions all drop via
    # CASCADE off the partitioned parent -- no separate DROP needed.
    op.execute("DROP TABLE IF EXISTS data_access_log CASCADE;")

    op.drop_index("ix_break_glass_grants_reviewed_by", table_name="break_glass_grants")
    op.drop_index("ix_break_glass_grants_revoked_by", table_name="break_glass_grants")
    op.drop_index("ix_break_glass_grants_granted_to_user_id", table_name="break_glass_grants")
    op.drop_index("ix_break_glass_grants_patient_id", table_name="break_glass_grants")
    op.drop_table("break_glass_grants")

    op.execute("DROP TRIGGER IF EXISTS trg_consent_withdrawals_flip_status ON consent_withdrawals;")
    op.execute("DROP FUNCTION IF EXISTS trg_consent_withdrawals_flip_status();")

    op.drop_index(
        "ix_consent_withdrawals_withdrawn_by_user_id", table_name="consent_withdrawals"
    )
    op.drop_index("ix_consent_withdrawals_consent_id", table_name="consent_withdrawals")
    op.drop_table("consent_withdrawals")

    op.execute("DROP TRIGGER IF EXISTS trg_consent_records_freeze ON consent_records;")
    op.execute("DROP FUNCTION IF EXISTS trg_consent_records_freeze();")

    op.drop_index("ix_consent_records_updated_by", table_name="consent_records")
    op.drop_index("ix_consent_records_created_by", table_name="consent_records")
    op.drop_index("ix_consent_records_granted_by_user_id", table_name="consent_records")
    op.drop_index("ix_consent_records_purpose_id", table_name="consent_records")
    op.drop_index("ix_consent_records_patient_id", table_name="consent_records")
    op.drop_table("consent_records")

    op.drop_table("consent_purposes")
