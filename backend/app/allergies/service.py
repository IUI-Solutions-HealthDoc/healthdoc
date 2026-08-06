"""Prescribing-time allergy check — schema v3.14 §3 0032.

The whole feature lives or dies on `check_prescription_item`. Read the docstring there
before changing anything.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies.models import Allergy
from app.common.enums import AllergyStatus

#: Minimum length for an override rationale. "ok" is not a clinical justification.
OVERRIDE_REASON_MIN_CHARS = 20


class AllergyConflict(Exception):
    """Raised when a prescribed item matches an active, coded patient allergy."""

    def __init__(self, allergy: Allergy) -> None:
        self.allergy = allergy
        self.absolute = allergy.is_absolute
        super().__init__(
            f"{allergy.substance_text} ({allergy.severity}): {allergy.reaction or 'no reaction recorded'}"
        )


async def active_allergies(db: AsyncSession, patient_id: uuid.UUID) -> list[Allergy]:
    """Everything the banner shows — coded and uncoded alike."""
    rows = await db.execute(
        select(Allergy).where(
            Allergy.patient_id == patient_id,
            Allergy.status == AllergyStatus.ACTIVE.value,
        )
    )
    return list(rows.scalars().all())


async def check_prescription_item(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    ingredient_code: str | None,
    override_reason: str | None = None,
) -> Allergy | None:
    """Check one prescribed item against the patient's allergies.

    Returns the matched allergy when an override was accepted (so the caller can record
    it), None when there was no conflict, and raises AllergyConflict otherwise.

    Two things here are deliberate and load-bearing:

    1. **The match is on ingredient_code, not inventory_item_id.** Amoxicillin and
       penicillin V are different stock items with the same ingredient; matching on the
       item would let the second one through for a patient who reacts to the first.

    2. **An item with no ingredient_code is not "clear", it is "unknown".** We return
       None because we cannot block on a guess, but the caller must tell the clinician
       the check could not be performed rather than implying it passed.
    """
    if ingredient_code is None:
        return None

    rows = await db.execute(
        select(Allergy).where(
            Allergy.patient_id == patient_id,
            Allergy.status == AllergyStatus.ACTIVE.value,
            Allergy.ingredient_code == ingredient_code,
        )
    )
    match = rows.scalars().first()
    if match is None:
        return None

    # Anaphylaxis is not a warning. No role, no reason, no override.
    if match.is_absolute:
        raise AllergyConflict(match)

    if override_reason is None or len(override_reason.strip()) < OVERRIDE_REASON_MIN_CHARS:
        raise AllergyConflict(match)

    return match
