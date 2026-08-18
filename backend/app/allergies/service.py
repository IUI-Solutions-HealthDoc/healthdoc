"""Prescribing-time allergy check — schema v3.14 §3 0032.

The whole feature lives or dies on `check_prescription_item`. Read the docstring there
before changing anything.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.allergies.models import Allergy
from app.allergies.schemas import AllergyCreate
from app.common.enums import AllergyStatus


OVERRIDE_REASON_MIN_CHARS = 20


class AllergyVersionConflict(Exception):
    """Raised when row_version has moved since the caller read the record."""


class AllergyConflict(Exception):
    """Raised when a prescribed item matches an active, coded patient allergy."""

    def __init__(self, allergy: Allergy) -> None:
        self.allergy = allergy
        self.absolute = allergy.is_absolute
        super().__init__(
            f"{allergy.substance_text} ({allergy.severity}): {allergy.reaction or 'no reaction recorded'}"
        )


async def get_allergy(db: AsyncSession, allergy_id: uuid.UUID) -> Allergy | None:
    return await db.get(Allergy, allergy_id)


async def list_allergies(
    db: AsyncSession, patient_id: uuid.UUID, *, include_inactive: bool = False
) -> list[Allergy]:
    """The register for one patient.

    Defaults to active only, because that is what a prescribing banner must show.
    `include_inactive=True` is for the record-review screen, where a refuted or
    erroneous entry still has to be visible — they are corrected, never deleted,
    so hiding them entirely would make the correction itself invisible.
    """
    stmt = select(Allergy).where(Allergy.patient_id == patient_id)
    if not include_inactive:
        stmt = stmt.where(Allergy.status == AllergyStatus.ACTIVE.value)
    rows = await db.execute(stmt.order_by(Allergy.created_at.desc()))
    return list(rows.scalars().all())


async def record_allergy(
    db: AsyncSession, payload: AllergyCreate, *, recorded_by: uuid.UUID
) -> Allergy:
    """New entry. Always starts `active` and unverified.

    recorded_by is the authenticated user, never the request body — a register
    entry whose author can be spoofed is worthless in an adverse-event review.
    """
    allergy = Allergy(
        # Explicit id, like every other writer in this codebase. The PK's
        # server_default is uuid_generate_v4(), which the test database cannot
        # return to the ORM — leaving the instance with no identity, so the
        # follow-up refresh selects on a NULL pk and finds nothing.
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        allergen_type=payload.allergen_type,
        substance_text=payload.substance_text,
        ingredient_code=payload.ingredient_code,
        inventory_item_id=payload.inventory_item_id,
        reaction=payload.reaction,
        severity=payload.severity,
        status=AllergyStatus.ACTIVE.value,
        onset_date=payload.onset_date,
        recorded_by=recorded_by,
        created_by=recorded_by,
    )
    db.add(allergy)
    await db.flush()
    await db.refresh(allergy)
    return allergy


async def set_status(
    db: AsyncSession,
    allergy_id: uuid.UUID,
    *,
    status: str,
    row_version: int,
    updated_by: uuid.UUID,
) -> Allergy | None:
    """Correct an entry. Returns None if it does not exist.

    Optimistic concurrency on row_version, same as patients: two clinicians
    reviewing the same register must not silently overwrite one another, and the
    loser needs to re-read before deciding again.
    """
    allergy = await db.get(Allergy, allergy_id)
    if allergy is None:
        return None
    if allergy.row_version != row_version:
        raise AllergyVersionConflict(
            f"row_version {row_version} is stale; current is {allergy.row_version}"
        )
    allergy.status = status
    allergy.row_version += 1
    allergy.updated_by = updated_by
    await db.flush()
    await db.refresh(allergy)
    return allergy


async def verify_allergy(
    db: AsyncSession, allergy_id: uuid.UUID, *, verified_by: uuid.UUID
) -> Allergy | None:
    """Clinician confirmation. Sets verified_by and verified_at together.

    The 0032 CHECK `verification_complete` requires both or neither, so these can
    never be written separately.
    """
    allergy = await db.get(Allergy, allergy_id)
    if allergy is None:
        return None
    allergy.verified_by = verified_by
    allergy.verified_at = datetime.now(timezone.utc)
    allergy.row_version += 1
    allergy.updated_by = verified_by
    await db.flush()
    await db.refresh(allergy)
    return allergy


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

