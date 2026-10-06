"""Share issued invoices to ABHA as InvoiceRecord documents.

Revision ID: 0094
Revises: 0093
Create Date: 2026-10-05

NHA's November 2025 HMIS FAQ asks for eight HI types, one of them billing.
fhir/builder.py now builds an NRCeS InvoiceRecord (ndhm.in 6.5.0, validated)
for an issued invoice, so the care-context CHECK widens by that one type; the
drift test keeps the CHECK, the builder and hip/gateway.HI_TYPES in agreement.

invoices.issued_at is the invoice's date as a document. updated_at moves with
every payment, and a care context's document date must not. It is set when
the invoice leaves draft and joins the columns trg_invoices_freeze holds
fixed. Invoices issued before this revision keep NULL and are not offered:
their issue time was never recorded, and a guessed one would be a false date.

Downgrade refuses while any invoice care context exists, as 0092 does.
"""

import sqlalchemy as sa
from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

_CONSTRAINT = "abdm_care_context_hi_type"
_WITH_INVOICE = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord','ImmunizationRecord','Invoice')"
)
_WITHOUT_INVOICE = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord','ImmunizationRecord')"
)


def _freeze(columns: str, old_columns: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION trg_invoices_freeze_fn() RETURNS trigger AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM 'draft' THEN
                IF ({columns})
                   IS DISTINCT FROM
                   ({old_columns})
                THEN
                    RAISE EXCEPTION
                        'invoices: cannot change frozen columns once an invoice leaves draft status (id=%)',
                        OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """


_FROZEN = (
    "invoice_number, visit_id, patient_id, facility_id, gross_amount, discount_amount, "
    "scheme_adjustment, net_amount, scheme_code"
)


def _cols(prefix: str, extra: str = "") -> str:
    return ", ".join(f"{prefix}.{c.strip()}" for c in (_FROZEN + extra).split(","))


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITH_INVOICE)
    op.add_column("invoices", sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(_freeze(_cols("NEW", ", issued_at"), _cols("OLD", ", issued_at")))


def downgrade() -> None:
    held = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM abdm_care_contexts WHERE hi_type = 'Invoice'")
    )
    if held:
        raise RuntimeError(
            f"{held} invoice care context(s) exist; they may already be linked "
            "to an ABHA address. Withdraw them explicitly before downgrading."
        )
    op.execute(_freeze(_cols("NEW"), _cols("OLD")))
    op.drop_column("invoices", "issued_at")
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITHOUT_INVOICE)
