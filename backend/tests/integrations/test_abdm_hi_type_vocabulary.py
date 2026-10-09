"""The three ABDM HI-type vocabularies must agree — a drift guard (F3).

Three places name the set of health-information types, and they used to
disagree:

  * fhir/builder.RECORD_TYPES     — what a bundle can actually be BUILT for
  * hip/gateway.HI_TYPES          — what an outbound call will ACCEPT
  * abdm_care_contexts.hi_type    — what can be STORED as a care context

When the CHECK and the validator were wider than the builder, a care context
stored as ImmunizationRecord or HealthDocumentRecord linked and discovered
normally and then failed at transfer with "No clinical mapper exists" — the
silent empty-shell failure mode this project keeps hitting. Nothing in the
suite noticed, because no test compared the three.

This test makes the three sets one fact. If you add a type to any one of them,
this fails until the other two agree — which is the point: a type you can store
but not build, or accept but not store, is a latent failed transfer.
"""
from __future__ import annotations

import re

from app.integrations.abdm.fhir.builder import RECORD_TYPES
from app.integrations.abdm.hip.gateway import HI_TYPES
from app.integrations.abdm.hip.models import AbdmCareContext


def _care_context_check_types() -> set[str]:
    """The literal HI types allowed by the abdm_care_contexts CHECK constraint."""
    for constraint in AbdmCareContext.__table__.constraints:
        # Only CheckConstraint has sqltext; it is a TextClause, so stringify it
        # explicitly rather than truth-testing it (a bare `or ""` raises).
        raw = getattr(constraint, "sqltext", None)
        if raw is None:
            continue
        text = str(raw)
        if "hi_type" in text and " IN " in text:
            return set(re.findall(r"'([^']+)'", text))
    raise AssertionError("no hi_type CHECK constraint found on abdm_care_contexts")


def test_builder_validator_and_check_name_the_same_hi_types():
    builder = set(RECORD_TYPES)
    validator = set(HI_TYPES)
    stored = _care_context_check_types()

    assert builder == validator, (
        "fhir/builder.RECORD_TYPES and hip/gateway.HI_TYPES disagree — a type "
        f"accepted but not buildable is a failed transfer. only_builder={builder - validator}, "
        f"only_validator={validator - builder}"
    )
    assert builder == stored, (
        "the abdm_care_contexts CHECK and the FHIR builder disagree — a type "
        f"storable but not buildable is a failed transfer. only_check={stored - builder}, "
        f"only_builder={builder - stored}"
    )


def test_all_eight_hmis_types_are_buildable_storable_and_accepted():
    """NHA's HMIS FAQ (November 2025) asks for eight HI types. Each came back
    with a builder, in all three places at once: ImmunizationRecord (0092),
    Invoice (0094), HealthDocumentRecord (0096)."""
    eight = {
        "OPConsultation", "Prescription", "DiagnosticReport", "DischargeSummary",
        "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
    }
    assert set(RECORD_TYPES) == eight
    assert set(HI_TYPES) == eight
    assert _care_context_check_types() == eight
