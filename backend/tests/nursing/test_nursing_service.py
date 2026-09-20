"""Nursing service tests (#390) — vitals, eMAR, fluid balance.

The behaviours worth pinning are the ones a future change could plausibly get
wrong without any test noticing:

  * BMI/WHR are derived, never client-supplied
  * the vitals series spans OPD and IPD for one patient
  * held/refused demand a reason
  * fluid balance reads direction from entry_type, not the sign of volume_ml
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.common.enums import MedicationAdministrationStatus
from app.nursing.schemas import (
    IntakeOutputCreate, MedicationAdministrationCreate, VitalsCreate,
)
from app.nursing.service import (
    fluid_balance, list_administrations, list_vitals, record_administration,
    record_intake_output, record_vitals, _bmi, _whr,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)


def _vitals(patient_id, **over):
    base = dict(patient_id=patient_id, encounter_id=uuid.uuid4(), measured_at=NOW)
    base.update(over)
    return VitalsCreate(**base)


# ---------------------------------------------------------------- derived values

async def test_bmi_is_computed_not_supplied():
    # 70kg at 1.75m -> 22.9
    assert _bmi(Decimal("175"), Decimal("70")) == Decimal("22.9")
    assert "bmi" not in VitalsCreate.model_fields, "BMI must not be settable by the client"
    assert "whr" not in VitalsCreate.model_fields


async def test_derived_values_are_none_when_inputs_are_missing():
    assert _bmi(None, Decimal("70")) is None
    assert _bmi(Decimal("175"), None) is None
    # Height of zero would be a division by zero rather than a BMI.
    assert _bmi(Decimal("0"), Decimal("70")) is None
    assert _whr(Decimal("80"), Decimal("0")) is None


async def test_record_vitals_stores_derived_bmi(db):
    patient_id = uuid.uuid4()
    v = await record_vitals(
        db, _vitals(patient_id, height_cm=Decimal("175"), weight_kg=Decimal("70")),
        recorded_by=uuid.uuid4(),
    )
    assert v.bmi == Decimal("22.9")


# ---------------------------------------------------------------- the series

async def test_vitals_series_spans_opd_and_ipd(db):
    """A patient seen in OPD and later admitted has vitals on both sides.

    ck_vitals_encounter_or_admission means each row hangs off exactly one, so a
    chart filtering on either column alone would silently drop half the trend.
    """
    patient_id = uuid.uuid4()
    actor = uuid.uuid4()

    await record_vitals(db, _vitals(patient_id, measured_at=NOW, pulse_bpm=80), recorded_by=actor)
    await record_vitals(
        db,
        VitalsCreate(patient_id=patient_id, admission_id=uuid.uuid4(),
                     measured_at=NOW + timedelta(hours=6), pulse_bpm=96),
        recorded_by=actor,
    )

    series = await list_vitals(db, patient_id)
    assert [v.pulse_bpm for v in series] == [80, 96], "oldest first, both contexts"


async def test_vitals_series_is_filtered_by_window(db):
    patient_id = uuid.uuid4()
    actor = uuid.uuid4()
    await record_vitals(db, _vitals(patient_id, measured_at=NOW - timedelta(days=3)), recorded_by=actor)
    await record_vitals(db, _vitals(patient_id, measured_at=NOW), recorded_by=actor)

    recent = await list_vitals(db, patient_id, since=NOW - timedelta(days=1))
    assert len(recent) == 1


async def test_vitals_requires_exactly_one_context():
    patient_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        VitalsCreate(patient_id=patient_id, measured_at=NOW)          # neither
    with pytest.raises(ValidationError):
        VitalsCreate(patient_id=patient_id, encounter_id=uuid.uuid4(),
                     admission_id=uuid.uuid4(), measured_at=NOW)      # both


async def test_diastolic_above_systolic_is_rejected():
    with pytest.raises(ValidationError):
        _vitals(uuid.uuid4(), bp_systolic=80, bp_diastolic=120)


# ---------------------------------------------------------------- eMAR

def _emar(admission_id, patient_id, **over):
    base = dict(
        prescription_item_id=uuid.uuid4(), admission_id=admission_id,
        patient_id=patient_id, status=MedicationAdministrationStatus.GIVEN.value,
    )
    base.update(over)
    return MedicationAdministrationCreate(**base)


async def _prescribed_item(db, patient_id, actor):
    from app.orders.models import Prescription, PrescriptionItem
    prescription = Prescription(id=uuid.uuid4(), encounter_id=uuid.uuid4(), facility_id=uuid.uuid4(),
                                patient_id=patient_id, created_by=actor)
    db.add(prescription)
    await db.flush()
    item = PrescriptionItem(id=uuid.uuid4(), prescription_id=prescription.id,
                            medicine_name="Synthetic test medicine", dosage="Recorded dose")
    db.add(item)
    await db.flush()
    return item


async def test_given_needs_no_reason(db):
    admission_id, patient_id = uuid.uuid4(), uuid.uuid4()
    actor = uuid.uuid4()
    item = await _prescribed_item(db, patient_id, actor)
    rec = await record_administration(db, _emar(admission_id, patient_id, prescription_item_id=item.id), recorded_by=actor)
    assert rec.status == "given"
    assert rec.reason is None


@pytest.mark.parametrize("status", ["held", "refused"])
async def test_held_and_refused_require_a_reason(status):
    """An unexplained missed dose is what an adverse-event review cannot
    reconstruct. Rejected at the schema so the caller gets a 422 naming the
    field; 0043's CHECK still refuses anything written around the API."""
    with pytest.raises(ValidationError):
        _emar(uuid.uuid4(), uuid.uuid4(), status=status)
    with pytest.raises(ValidationError):
        _emar(uuid.uuid4(), uuid.uuid4(), status=status, reason="   ")

    ok = _emar(uuid.uuid4(), uuid.uuid4(), status=status, reason="BP 80/50, held per protocol")
    assert ok.reason


async def test_unknown_status_is_rejected():
    with pytest.raises(ValidationError):
        _emar(uuid.uuid4(), uuid.uuid4(), status="administered")


async def test_emar_lists_most_recent_first(db):
    admission_id, patient_id, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    item = await _prescribed_item(db, patient_id, actor)
    await record_administration(
        db, _emar(admission_id, patient_id, prescription_item_id=item.id, administered_at=NOW), recorded_by=actor)
    await record_administration(
        db, _emar(admission_id, patient_id, prescription_item_id=item.id, administered_at=NOW + timedelta(hours=8),
                  status="refused", reason="patient declined"),
        recorded_by=actor)

    rows = await list_administrations(db, admission_id)
    assert [r.status for r in rows] == ["refused", "given"]


# ---------------------------------------------------------------- fluid balance

async def test_fluid_balance_uses_entry_type_not_sign(db):
    """volume_ml is positive by CHECK; direction comes from the intake_/output_
    prefix. A new IntakeOutputType that breaks that convention would land in
    neither total, which is why this asserts the arithmetic and not just a sum."""
    admission_id, actor = uuid.uuid4(), uuid.uuid4()
    for entry_type, volume in [
        ("intake_oral", 500), ("intake_iv", 1000),
        ("output_urine", 900), ("output_drain", 100),
    ]:
        await record_intake_output(
            db, IntakeOutputCreate(admission_id=admission_id, entry_type=entry_type,
                                   volume_ml=volume, recorded_at=NOW),
            recorded_by=actor,
        )

    balance = await fluid_balance(db, admission_id)
    assert balance["total_intake_ml"] == 1500
    assert balance["total_output_ml"] == 1000
    assert balance["net_ml"] == 500


async def test_fluid_balance_of_an_admission_with_no_records_is_zero(db):
    balance = await fluid_balance(db, uuid.uuid4())
    assert balance == {
        "admission_id": balance["admission_id"],
        "total_intake_ml": 0, "total_output_ml": 0, "net_ml": 0,
    }


async def test_emar_rows_name_their_drug(db):
    """An eMAR carrying only prescription_item_id cannot say what was given.

    The screen would otherwise have to fetch every prescription item
    separately — one request per row of the table a nurse reads most.
    """
    from app.orders.models import Prescription, PrescriptionItem

    admission_id, patient_id, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    prescription = Prescription(
        id=uuid.uuid4(), encounter_id=uuid.uuid4(), facility_id=uuid.uuid4(),
        patient_id=patient_id, created_by=actor,
    )
    db.add(prescription)
    await db.flush()

    item = PrescriptionItem(
        id=uuid.uuid4(), prescription_id=prescription.id,
        medicine_name="Amoxicillin 500mg", dosage="500mg", route="oral",
    )
    db.add(item)
    await db.flush()

    await record_administration(
        db,
        _emar(admission_id, patient_id, prescription_item_id=item.id),
        recorded_by=actor,
    )

    (row,) = await list_administrations(db, admission_id)
    assert row.medicine_name == "Amoxicillin 500mg"
    assert row.dosage == "500mg", "the prescribed dose"
    assert row.route == "oral"


async def test_a_dose_survives_a_missing_prescription_item(db):
    """LEFT join, deliberately. A dose that was actually given must not vanish
    from the record because the item it referenced is gone — the name goes
    unknown, the administration stays."""
    admission_id, patient_id = uuid.uuid4(), uuid.uuid4()
    # Deliberately seed a broken historical reference for the read test; new
    # administration writes must not be allowed to create that inconsistency.
    from app.nursing.models import MedicationAdministration
    db.add(MedicationAdministration(
        id=uuid.uuid4(), prescription_item_id=uuid.uuid4(), admission_id=admission_id,
        patient_id=patient_id, status="given", administered_at=NOW, created_by=uuid.uuid4(),
    ))
    await db.flush()

    (row,) = await list_administrations(db, admission_id)
    assert row.medicine_name is None
    assert row.status == "given", "the administration is still on the record"


async def test_negative_or_zero_volume_is_rejected():
    for bad in (0, -100):
        with pytest.raises(ValidationError):
            IntakeOutputCreate(admission_id=uuid.uuid4(), entry_type="intake_oral", volume_ml=bad)


async def test_no_delete_endpoint_exists():
    """Nursing observations are corrected by a new entry, never removed."""
    from app.nursing.router import router

    verbs = {m for r in router.routes for m in getattr(r, "methods", set())}
    assert "DELETE" not in verbs
