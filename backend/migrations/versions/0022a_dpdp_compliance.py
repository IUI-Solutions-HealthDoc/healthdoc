"""0022a dpdp_compliance

Revision ID: 0022a
Revises: 0022
Create Date: 2026-08-11

Originally 0021/down_revision=0020c. Renumbered per Tech Lead (PR #359):
0021/0022 went to Aditya's encounter_soap/order_number_counters (written,
tested, ready to merge -- "ready work takes the slots"), this moves to
0022a as an out-of-band insert, same convention as 0003a and 0020a-c.
0022 (order_number_counters) is itself not merged yet at the time of this
rename -- expected mid-flight per §2's own "set down_revision to its
number anyway and coordinate merge order" rule, same situation this
migration's own dependents will eventually be in.

Builds: data_protection_officers, patient_grievances, data_breach_notifications,
consent_managers (schema doc §3, "0021-0026 -- Compliance & operations wave").
Also: ALTER consent_records ADD consent_manager_id -> consent_managers.

Depends on: 0002 (facilities, users), 0004 (consent_records), 0006 (patients) --
all already merged.

Migration-only, no ORM models. Matches the precedent in 0015's own docstring:
models and migrations for a table sometimes land as separate pieces of work.
grievance_number/breach_number generation (format: GRV-<FACILITY>-<YYYYMMDD>-<SEQ4>)
is service-layer work, not this migration's concern -- the column here is just
UNIQUE NOT NULL, same split as billing_counters (0014) vs. the actual
_allocate_billing_number() logic that came with the invoice-builder ticket.

Enum-backed columns (grievance_type, status x2) use the generated
.sql_check() from app.common.enums (GrievanceType, GrievanceStatus,
BreachStatus already exist there) rather than a hardcoded IN-list, so this
migration and those classes can't drift. All are varchar(50) per the v3.4.1
blanket width rule -- the source PDF (v3.13) still shows varchar(30) for
these; v3.13 predates that rule, this migration follows the current
docs/database-schema.md (v3.16).

TRIGGER NOTE: data_breach_notifications' "append-only after status closes"
means mutable (UPDATE and DELETE both allowed) while status != 'closed' --
required, since certin_reported_at/dpb_first_intimation_at/
dpb_detailed_report_at/patients_notified_at/mitigation_measures/root_cause
are all filled in progressively as an incident investigation unfolds -- and
frozen (no UPDATE, no DELETE) once status = 'closed'. Same "mutable until a
terminal state" shape as trg_invoices_freeze (0014), inverted: freeze is
keyed off reaching the terminal state, not off leaving the initial one.

TRG_CONSENT_RECORDS_FREEZE UPDATE: the new consent_manager_id column is NOT
automatically covered by 0004's trg_consent_records_freeze -- that trigger
raises only when one of its explicitly-named columns changes, so a column
added later and left out of that list would be silently exempt from the
freeze, not caught as an unexpected mutation. Re-declared here via CREATE OR
REPLACE (same function name, so the existing trigger picks it up with no
separate DROP/CREATE TRIGGER) to add consent_manager_id to the immutable set,
consistent with every other non-status column on that table. downgrade()
restores the original 0004 body before dropping the column, so a rollback
never leaves the function referencing a column that no longer exists.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.enums import BreachStatus, GrievanceStatus, GrievanceType

revision = "0022a"
down_revision = "0022"
branch_labels = None
depends_on = None

_GRIEVANCE_TYPE_CHECK = GrievanceType.sql_check("grievance_type")
_GRIEVANCE_STATUS_CHECK = GrievanceStatus.sql_check("status")
_BREACH_STATUS_CHECK = BreachStatus.sql_check("status")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. data_protection_officers
    # ------------------------------------------------------------------
    op.create_table(
        "data_protection_officers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT",
                                name="fk_data_protection_officers_facility_id"),
                  nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_data_protection_officers_user_id"),
                  nullable=False),
        sa.Column("appointed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("contact_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_contact", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_data_protection_officers_created_by"),
                  nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_data_protection_officers_updated_by"),
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_data_protection_officers_user_id", "data_protection_officers", ["user_id"])
    op.create_index("ix_data_protection_officers_created_by", "data_protection_officers", ["created_by"])
    op.create_index("ix_data_protection_officers_updated_by", "data_protection_officers", ["updated_by"])
    # Only one active DPO per facility -- doc-specified name, kept verbatim
    # rather than the table-derived convention (uq_data_protection_officers_...).
    op.create_index(
        "uq_dpo_active_facility", "data_protection_officers", ["facility_id"],
        unique=True, postgresql_where=sa.text("is_active"),
    )

    # ------------------------------------------------------------------
    # 2. patient_grievances
    # ------------------------------------------------------------------
    op.create_table(
        "patient_grievances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        # GRV-<FACILITY>-<YYYYMMDD>-<SEQ4> -- generated by the service
        # layer, not this migration. See module docstring.
        sa.Column("grievance_number", sa.String(30), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("patients.id", ondelete="RESTRICT",
                                name="fk_patient_grievances_patient_id"),
                  nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT",
                                name="fk_patient_grievances_facility_id"),
                  nullable=False),
        sa.Column("grievance_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_patient_grievances_assigned_to"),
                  nullable=True),
        # created_at + 90 days -- app-set at insert time, not a DB default.
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_patient_grievances_created_by"),
                  nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT",
                                name="fk_patient_grievances_updated_by"),
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("grievance_number", name="uq_patient_grievances_grievance_number"),
        sa.CheckConstraint(_GRIEVANCE_TYPE_CHECK, name="ck_patient_grievances_grievance_type"),
        sa.CheckConstraint(_GRIEVANCE_STATUS_CHECK, name="ck_patient_grievances_status"),
    )
    op.create_index("ix_patient_grievances_patient_id", "patient_grievances", ["patient_id"])
    op.create_index("ix_patient_grievances_facility_id", "patient_grievances", ["facility_id"])
    op.create_index("ix_patient_grievances_assigned_to", "patient_grievances", ["assigned_to"])
    op.create_index("ix_patient_grievances_created_by", "patient_grievances", ["created_by"])
    op.create_index("ix_patient_grievances_updated_by", "patient_grievances", ["updated_by"])
    op.create_index("ix_patient_grievances_status_due_at", "patient_grievances", ["status", "due_at"])

    # ------------------------------------------------------------------
    # 3. data_breach_notifications -- mutable until status='closed', then
    #    frozen (see module docstring for why UPDATE fields exist at all).
    # ------------------------------------------------------------------
    op.create_table(
        "data_breach_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("breach_number", sa.String(30), nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("certin_reported_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dpb_first_intimation_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dpb_detailed_report_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("patients_notified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("affected_patients_count", sa.Integer(), nullable=True),
        sa.Column("nature", sa.Text(), nullable=False),
        sa.Column("extent", sa.Text(), nullable=True),
        sa.Column("mitigation_measures", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("facilities.id", ondelete="RESTRICT",
                                name="fk_data_breach_notifications_facility_id"),
                  nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("breach_number", name="uq_data_breach_notifications_breach_number"),
        sa.CheckConstraint(_BREACH_STATUS_CHECK, name="ck_data_breach_notifications_status"),
    )
    op.create_index("ix_data_breach_notifications_facility_id", "data_breach_notifications", ["facility_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_data_breach_notifications_freeze_when_closed() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'closed' THEN
                RAISE EXCEPTION
                    'data_breach_notifications % is closed and immutable, % not permitted',
                    OLD.id, TG_OP;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_data_breach_notifications_freeze_when_closed
        BEFORE UPDATE OR DELETE ON data_breach_notifications
        FOR EACH ROW EXECUTE FUNCTION trg_data_breach_notifications_freeze_when_closed();
        """
    )

    # ------------------------------------------------------------------
    # 4. consent_managers -- global registry, not facility-scoped (DPDP-
    #    registered intermediaries / ABDM CMs operate across facilities).
    # ------------------------------------------------------------------
    op.create_table(
        "consent_managers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("cm_registration_id", sa.String(100), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("cm_registration_id", name="uq_consent_managers_cm_registration_id"),
    )

    # ------------------------------------------------------------------
    # 5. consent_records.consent_manager_id (deferred FK to consent_managers,
    #    which didn't exist until this migration) + freeze-trigger update.
    # ------------------------------------------------------------------
    op.add_column(
        "consent_records",
        sa.Column("consent_manager_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_consent_records_consent_manager_id", "consent_records", "consent_managers",
        ["consent_manager_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_consent_records_consent_manager_id", "consent_records", ["consent_manager_id"])

    # See module docstring: consent_manager_id must join the immutable
    # set trg_consent_records_freeze already enforces, or it's silently
    # exempt from it.
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
               OR NEW.consent_manager_id         IS DISTINCT FROM OLD.consent_manager_id
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


def downgrade() -> None:
    # Restore the original 0004-era freeze function BEFORE dropping the
    # column it would otherwise still reference.
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

    op.drop_index("ix_consent_records_consent_manager_id", table_name="consent_records")
    op.drop_constraint("fk_consent_records_consent_manager_id", "consent_records", type_="foreignkey")
    op.drop_column("consent_records", "consent_manager_id")

    op.drop_table("consent_managers")

    op.execute("DROP TRIGGER IF EXISTS trg_data_breach_notifications_freeze_when_closed ON data_breach_notifications;")
    op.execute("DROP FUNCTION IF EXISTS trg_data_breach_notifications_freeze_when_closed();")
    op.drop_index("ix_data_breach_notifications_facility_id", table_name="data_breach_notifications")
    op.drop_table("data_breach_notifications")

    op.drop_index("ix_patient_grievances_status_due_at", table_name="patient_grievances")
    op.drop_index("ix_patient_grievances_updated_by", table_name="patient_grievances")
    op.drop_index("ix_patient_grievances_created_by", table_name="patient_grievances")
    op.drop_index("ix_patient_grievances_assigned_to", table_name="patient_grievances")
    op.drop_index("ix_patient_grievances_facility_id", table_name="patient_grievances")
    op.drop_index("ix_patient_grievances_patient_id", table_name="patient_grievances")
    op.drop_table("patient_grievances")

    op.drop_index("uq_dpo_active_facility", table_name="data_protection_officers")
    op.drop_index("ix_data_protection_officers_updated_by", table_name="data_protection_officers")
    op.drop_index("ix_data_protection_officers_created_by", table_name="data_protection_officers")
    op.drop_index("ix_data_protection_officers_user_id", table_name="data_protection_officers")
    op.drop_table("data_protection_officers")
