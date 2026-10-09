"""Share a released patient document to ABHA as a HealthDocumentRecord.

Revision ID: 0096
Revises: 0095
Create Date: 2026-10-08

NHA's HMIS FAQ (November 2025) asks for all eight HI types; the one HealthDoc
could not build was HealthDocumentRecord, a document held as a file rather
than written as structured data (a referral letter, an outside report, a
scanned history). Uploading a file to a chart does not make it shareable:
abdm_released_documents records the clinician's explicit decision to release
one uploaded PDF, with the title and date the patient will see. One file is
released at most once, so its care-context reference never changes.

The care-context CHECK widens by that one type; the drift test keeps the
CHECK, fhir/builder.RECORD_TYPES and hip/gateway.HI_TYPES in agreement.

Downgrade refuses while any HealthDocumentRecord care context exists: it may
already be linked to an ABHA address, as 0092 and 0094 do.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None

_CONSTRAINT = "abdm_care_context_hi_type"
_WITHOUT = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord','ImmunizationRecord','Invoice')"
)
_WITH = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord','ImmunizationRecord','Invoice',"
    "'HealthDocumentRecord')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITH)
    op.create_table(
        "abdm_released_documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "facility_id",
            UUID(as_uuid=True),
            sa.ForeignKey("facilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column(
            "released_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "released_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("file_id", name="uq_abdm_released_documents_file_id"),
        sa.CheckConstraint("trim(title) <> ''", name="ck_abdm_released_documents_title"),
    )
    op.create_index(
        "ix_abdm_released_documents_facility_id", "abdm_released_documents", ["facility_id"]
    )
    op.create_index(
        "ix_abdm_released_documents_patient_id", "abdm_released_documents", ["patient_id"]
    )
    op.create_index(
        "ix_abdm_released_documents_released_by", "abdm_released_documents", ["released_by"]
    )


def downgrade() -> None:
    held = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM abdm_care_contexts WHERE hi_type = 'HealthDocumentRecord'")
    )
    if held:
        raise RuntimeError(
            f"{held} HealthDocumentRecord care context(s) exist; they may already be "
            "linked to an ABHA address. Withdraw them explicitly before downgrading."
        )
    op.drop_table("abdm_released_documents")
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITHOUT)
