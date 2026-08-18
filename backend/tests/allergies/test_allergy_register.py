"""Register CRUD for #286 — the read/write side of 0032.

check_prescription_item (the gate) is already covered in tests/orders and
tests/pharmacy. These cover the part that had no API until now, and in
particular the two rules that are easy to regress:

  * entries are corrected, never deleted
  * verified_by and verified_at move together, because 0032's
    `verification_complete` CHECK rejects one without the other
"""
from __future__ import annotations

import uuid

import pytest

from app.allergies.models import Allergy
from app.allergies.schemas import AllergyCreate
from app.allergies.service import (
    AllergyVersionConflict,
    list_allergies,
    record_allergy,
    set_status,
    verify_allergy,
)
from app.common.enums import AllergenType, AllergySeverity, AllergyStatus


def _payload(patient_id: uuid.UUID, **over) -> AllergyCreate:
    base = dict(
        patient_id=patient_id,
        allergen_type=AllergenType.DRUG.value,
        substance_text="Penicillin injection",
        ingredient_code="ING_PEN",
        severity=AllergySeverity.MODERATE.value,
    )
    base.update(over)
    return AllergyCreate(**base)


@pytest.mark.asyncio
async def test_record_starts_active_and_unverified(db):
    patient_id, doctor_id = uuid.uuid4(), uuid.uuid4()

    allergy = await record_allergy(db, _payload(patient_id), recorded_by=doctor_id)

    assert allergy.status == AllergyStatus.ACTIVE.value
    assert allergy.recorded_by == doctor_id
    # Unverified until a clinician says otherwise — recording what an attendant
    # reports is not the same as confirming it.
    assert allergy.verified_by is None
    assert allergy.verified_at is None


@pytest.mark.asyncio
async def test_recorded_by_comes_from_the_caller_not_the_payload(db):
    """AllergyCreate has no recorded_by field at all, by design."""
    assert "recorded_by" not in AllergyCreate.model_fields


@pytest.mark.asyncio
async def test_uncoded_allergy_is_stored_and_listed_but_not_blocking(db):
    patient_id = uuid.uuid4()

    allergy = await record_allergy(
        db,
        _payload(patient_id, ingredient_code=None, substance_text="something in an injection"),
        recorded_by=uuid.uuid4(),
    )

    # Real, shown in the banner, and unmatchable — "could not check", not "clear".
    assert allergy.ingredient_code is None
    assert allergy.is_blocking is False
    assert allergy in await list_allergies(db, patient_id)


@pytest.mark.asyncio
async def test_list_hides_corrected_entries_unless_asked(db):
    patient_id = uuid.uuid4()
    allergy = await record_allergy(db, _payload(patient_id), recorded_by=uuid.uuid4())

    await set_status(
        db, allergy.id, status=AllergyStatus.ENTERED_IN_ERROR.value,
        row_version=allergy.row_version, updated_by=uuid.uuid4(),
    )

    assert await list_allergies(db, patient_id) == []
    # Still visible on review: a correction that hides itself is not a correction.
    assert len(await list_allergies(db, patient_id, include_inactive=True)) == 1


@pytest.mark.asyncio
async def test_stale_row_version_is_rejected(db):
    """Two clinicians on the same register must not silently overwrite each other."""
    allergy = await record_allergy(db, _payload(uuid.uuid4()), recorded_by=uuid.uuid4())
    first_read = allergy.row_version

    await set_status(
        db, allergy.id, status=AllergyStatus.INACTIVE.value,
        row_version=first_read, updated_by=uuid.uuid4(),
    )

    with pytest.raises(AllergyVersionConflict):
        await set_status(
            db, allergy.id, status=AllergyStatus.REFUTED.value,
            row_version=first_read, updated_by=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_verify_sets_both_halves_together(db):
    """0032's verification_complete CHECK is `(verified_by IS NULL) = (verified_at IS NULL)`."""
    allergy = await record_allergy(db, _payload(uuid.uuid4()), recorded_by=uuid.uuid4())
    doctor_id = uuid.uuid4()

    verified = await verify_allergy(db, allergy.id, verified_by=doctor_id)

    assert verified is not None
    assert verified.verified_by == doctor_id
    assert verified.verified_at is not None


@pytest.mark.asyncio
async def test_no_delete_endpoint_exists(db):
    """A deleted allergy that was real is the failure mode the status enum prevents."""
    from app.allergies.router import router

    verbs = {m for r in router.routes for m in getattr(r, "methods", set())}
    assert "DELETE" not in verbs


@pytest.mark.asyncio
async def test_missing_allergy_returns_none_rather_than_raising(db):
    assert await verify_allergy(db, uuid.uuid4(), verified_by=uuid.uuid4()) is None
    assert await set_status(
        db, uuid.uuid4(), status=AllergyStatus.INACTIVE.value,
        row_version=1, updated_by=uuid.uuid4(),
    ) is None
