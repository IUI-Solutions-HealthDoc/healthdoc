"""Narrow abdm_care_contexts.hi_type to the types the FHIR builder can populate.

The care-context CHECK admitted seven HI types; fhir/builder.py builds only
five. A context stored as ImmunizationRecord or HealthDocumentRecord linked and
discovered normally, then failed at transfer with "No clinical mapper exists" —
the silent empty-shell failure mode. This aligns the DB CHECK with the builder
and the outbound validator (hip/gateway.HI_TYPES); a drift test now keeps the
three in agreement.

Safe to apply: abdm_care_contexts is empty at the time of writing, and the
narrowed set is a strict subset, so no existing row can violate the new CHECK.
Re-widen only when the builder gains a mapper for the removed type.
"""

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

# The short constraint token, NOT the full name. Base.metadata's naming
# convention (ck_%(table_name)s_%(constraint_name)s) is active in migrations, so
# alembic expands this to ck_abdm_care_contexts_abdm_care_context_hi_type for
# both drop and create — exactly the name 0055's create_table produced. Passing
# the already-expanded name here would get wrapped a second time.
_CONSTRAINT = "abdm_care_context_hi_type"
_NARROW = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','WellnessRecord')"
)
_WIDE = (
    "hi_type IN ('OPConsultation','Prescription','DiagnosticReport',"
    "'DischargeSummary','ImmunizationRecord','HealthDocumentRecord','WellnessRecord')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _NARROW)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "abdm_care_contexts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "abdm_care_contexts", _WIDE)
