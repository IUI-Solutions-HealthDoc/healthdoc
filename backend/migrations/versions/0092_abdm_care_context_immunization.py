"""Let abdm_care_contexts hold ImmunizationRecord documents.

Revision ID: 0092
Revises: 0091
Create Date: 2026-10-02

0059 removed ImmunizationRecord because fhir/builder.py could not build it.
It now can: one NRCeS ImmunizationRecord per recorded vaccine dose, validated
against ndhm.in 6.5.0. The CHECK widens by exactly that one type; the drift
test keeps the CHECK, the builder and hip/gateway.HI_TYPES in agreement.

Downgrade refuses while any immunization care context exists. Narrowing the
CHECK under such a row would fail anyway, and deleting a context a patient may
already have linked would silently withdraw a shared record.
"""

import sqlalchemy as sa
from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None

# The short token; the metadata naming convention expands it to the full
# ck_abdm_care_contexts_abdm_care_context_hi_type name (see 0059).
_CONSTRAINT = "abdm_care_context_hi_type"
_WITH_IMMUNIZATION = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord','ImmunizationRecord')"
)
_WITHOUT_IMMUNIZATION = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITH_IMMUNIZATION)


def downgrade() -> None:
    held = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM abdm_care_contexts WHERE hi_type = 'ImmunizationRecord'")
    )
    if held:
        raise RuntimeError(
            f"{held} immunization care context(s) exist; they may already be linked "
            "to an ABHA address. Withdraw them explicitly before downgrading."
        )
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WITHOUT_IMMUNIZATION)
