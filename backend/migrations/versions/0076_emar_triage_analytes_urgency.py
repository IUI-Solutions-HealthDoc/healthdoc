"""eMAR dose identity, ED triage, structured lab analytes, and order urgency (HD-17 to HD-20).

Revision ID: 0076
Revises: 0075
Create Date: 2026-09-19
"""

import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- 1. eMAR DOSE IDENTITY & CORRECTIONS (HD-17 & HD-20) ----------------
    op.add_column(
        "medication_administration",
        sa.Column(
            "correction_of_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("medication_administration.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "medication_administration",
        sa.Column("is_correction", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "medication_administration",
        sa.Column("correction_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "medication_administration",
        sa.Column("route", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "medication_administration",
        sa.Column("requires_acknowledgement", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "medication_administration",
        sa.Column(
            "acknowledged_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "medication_administration",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_medication_administration_correction_of_id",
        "medication_administration",
        ["correction_of_id"],
    )
    op.create_index(
        "ix_medication_administration_acknowledged_by",
        "medication_administration",
        ["acknowledged_by"],
    )

    # ---------------- 2. PRESCRIPTION ITEM PRIORITY (HD-20) ----------------
    op.add_column(
        "prescription_items",
        sa.Column("priority", sa.String(length=50), nullable=False, server_default="routine"),
    )
    op.create_index("ix_prescription_items_priority", "prescription_items", ["priority"])

    # ---------------- 3. EMERGENCY TRIAGE & RETRIAGE LOGS (HD-18) ----------------
    op.create_table(
        "emergency_triages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "facility_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("visits.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("acuity_level", sa.String(length=50), nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=False),
        sa.Column("triage_notes", sa.Text(), nullable=True),
        sa.Column(
            "assigned_doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("assigned_bay", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="waiting"),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "triaged_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("clinician_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition", sa.String(length=50), nullable=True),
        sa.Column("disposition_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    op.create_index("ix_emergency_triages_facility_id", "emergency_triages", ["facility_id"])
    op.create_index("ix_emergency_triages_patient_id", "emergency_triages", ["patient_id"])
    op.create_index("ix_emergency_triages_visit_id", "emergency_triages", ["visit_id"])
    op.create_index("ix_emergency_triages_assigned_doctor_id", "emergency_triages", ["assigned_doctor_id"])
    op.create_index("ix_emergency_triages_triaged_by", "emergency_triages", ["triaged_by"])
    op.create_index("ix_emergency_triages_created_by", "emergency_triages", ["created_by"])
    op.create_index("ix_emergency_triages_updated_by", "emergency_triages", ["updated_by"])
    op.create_index("ix_emergency_triages_facility_status", "emergency_triages", ["facility_id", "status"])

    op.create_table(
        "emergency_triage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "triage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emergency_triages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("previous_acuity", sa.String(length=50), nullable=False),
        sa.Column("new_acuity", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "changed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_emergency_triage_logs_triage_id", "emergency_triage_logs", ["triage_id"])
    op.create_index("ix_emergency_triage_logs_changed_by", "emergency_triage_logs", ["changed_by"])

    # ---------------- 4. STRUCTURED LAB ANALYTES (HD-19) ----------------
    lab_analytes = op.create_table(
        "lab_analytes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("test_code", sa.String(length=50), nullable=False),
        sa.Column("analyte_code", sa.String(length=50), nullable=False),
        sa.Column("analyte_name", sa.String(length=100), nullable=False),
        sa.Column("value_type", sa.String(length=50), nullable=False, server_default="numeric"),

        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("reference_low", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("reference_high", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("critical_low", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("critical_high", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("test_code", "analyte_code", "version", name="uq_lab_analytes_test_code_analyte_version"),
    )
    op.create_index("ix_lab_analytes_test_code_version", "lab_analytes", ["test_code", "version"])

    # Standard Seed Analytes for Routine Diagnostic Panels
    now = datetime.now(timezone.utc)
    seed_analytes = [
        # Complete Blood Count (CBC)
        {"id": uuid.uuid4(), "test_code": "CBC", "analyte_code": "HB", "analyte_name": "Hemoglobin", "value_type": "numeric", "unit": "g/dL", "reference_low": 12.0, "reference_high": 17.5, "critical_low": 7.0, "critical_high": 20.0, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "CBC", "analyte_code": "WBC", "analyte_name": "Total Leucocyte Count", "value_type": "numeric", "unit": "10^3/uL", "reference_low": 4.0, "reference_high": 11.0, "critical_low": 2.0, "critical_high": 30.0, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "CBC", "analyte_code": "PLT", "analyte_name": "Platelet Count", "value_type": "numeric", "unit": "10^3/uL", "reference_low": 150.0, "reference_high": 450.0, "critical_low": 50.0, "critical_high": 1000.0, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "CBC", "analyte_code": "RBC", "analyte_name": "Red Blood Cells", "value_type": "numeric", "unit": "10^6/uL", "reference_low": 4.2, "reference_high": 5.9, "critical_low": 2.5, "critical_high": 7.0, "is_required": True, "version": 1, "created_at": now},
        # Electrolytes
        {"id": uuid.uuid4(), "test_code": "ELECTROLYTES", "analyte_code": "NA", "analyte_name": "Sodium", "value_type": "numeric", "unit": "mmol/L", "reference_low": 135.0, "reference_high": 145.0, "critical_low": 120.0, "critical_high": 160.0, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "ELECTROLYTES", "analyte_code": "K", "analyte_name": "Potassium", "value_type": "numeric", "unit": "mmol/L", "reference_low": 3.5, "reference_high": 5.1, "critical_low": 2.8, "critical_high": 6.2, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "ELECTROLYTES", "analyte_code": "CL", "analyte_name": "Chloride", "value_type": "numeric", "unit": "mmol/L", "reference_low": 96.0, "reference_high": 106.0, "critical_low": 80.0, "critical_high": 120.0, "is_required": True, "version": 1, "created_at": now},
        # Renal Function Test (RFT)
        {"id": uuid.uuid4(), "test_code": "RFT", "analyte_code": "CREAT", "analyte_name": "Serum Creatinine", "value_type": "numeric", "unit": "mg/dL", "reference_low": 0.7, "reference_high": 1.3, "critical_low": 0.3, "critical_high": 5.0, "is_required": True, "version": 1, "created_at": now},
        {"id": uuid.uuid4(), "test_code": "RFT", "analyte_code": "UREA", "analyte_name": "Blood Urea", "value_type": "numeric", "unit": "mg/dL", "reference_low": 15.0, "reference_high": 45.0, "critical_low": 5.0, "critical_high": 100.0, "is_required": True, "version": 1, "created_at": now},
    ]
    op.bulk_insert(lab_analytes, seed_analytes)


def downgrade() -> None:
    op.drop_index("ix_lab_analytes_test_code_version", table_name="lab_analytes")
    op.drop_table("lab_analytes")

    op.drop_index("ix_emergency_triage_logs_changed_by", table_name="emergency_triage_logs")
    op.drop_index("ix_emergency_triage_logs_triage_id", table_name="emergency_triage_logs")
    op.drop_table("emergency_triage_logs")

    op.drop_index("ix_emergency_triages_facility_status", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_updated_by", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_created_by", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_triaged_by", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_assigned_doctor_id", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_visit_id", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_patient_id", table_name="emergency_triages")
    op.drop_index("ix_emergency_triages_facility_id", table_name="emergency_triages")
    op.drop_table("emergency_triages")

    op.drop_index("ix_prescription_items_priority", table_name="prescription_items")
    op.drop_column("prescription_items", "priority")

    op.drop_index("ix_medication_administration_acknowledged_by", table_name="medication_administration")
    op.drop_index("ix_medication_administration_correction_of_id", table_name="medication_administration")
    op.drop_column("medication_administration", "acknowledged_at")
    op.drop_column("medication_administration", "acknowledged_by")
    op.drop_column("medication_administration", "requires_acknowledgement")
    op.drop_column("medication_administration", "route")
    op.drop_column("medication_administration", "correction_reason")
    op.drop_column("medication_administration", "is_correction")
    op.drop_column("medication_administration", "correction_of_id")
