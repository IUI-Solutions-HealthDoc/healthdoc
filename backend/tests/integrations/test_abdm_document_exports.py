"""Clinical rows, not mocked facts: one finalized document per care context."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.admissions.models import Discharge
from app.integrations.abdm.external_router import _contexts
from app.integrations.abdm.fhir.builder import build_clinical_bundle
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_document
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.hip.worker import TransferError, _clinical_facts
from app.nursing.models import Vitals
from app.opd.models import Encounter
from app.orders.models import Order, Prescription, PrescriptionItem
from app.pathology.models import LabOrderItem, LabResult
from app.radiology.models import RadiologyOrderItem, RadiologyReport
from app.users.models import Facility


@pytest.fixture
async def documents(db, seed, opd_visit):
    dept, _, doctor = seed
    visit = await opd_visit()
    facility = await db.get(Facility, dept.facility_id)
    facility.hfr_facility_id = "TEST-HFR"
    doctor.registration_number = "TEST-REG"
    now = datetime.now(UTC)
    encounters, prescriptions = [], []
    for index in range(2):
        encounter = Encounter(
            id=uuid.uuid4(),
            visit_id=visit.id,
            facility_id=facility.id,
            provider_user_id=doctor.id,
            started_at=now - timedelta(hours=2),
            ended_at=now,
            created_by=doctor.id,
            chief_complaint=f"Complaint {index}",
            plan=f"Plan {index}",
        )
        db.add(encounter)
        encounters.append(encounter)
        # Two prescriptions in each encounter catches both visit-wide and
        # encounter-wide leakage from a single selected prescription.
        for number in range(2):
            prescription = Prescription(
                id=uuid.uuid4(),
                encounter_id=encounter.id,
                patient_id=visit.patient_id,
                facility_id=facility.id,
                created_by=doctor.id,
                created_at=now - timedelta(minutes=1),
            )
            db.add_all(
                [
                    prescription,
                    PrescriptionItem(
                        id=uuid.uuid4(),
                        prescription_id=prescription.id,
                        medicine_name=f"Test medicine {index}-{number}",
                        dosage="1 tablet",
                    ),
                ]
            )
            prescriptions.append(prescription)
    results = {}
    for kind in ("lab-result", "radiology-report"):
        rows = []
        for number in range(2):
            order = Order(
                id=uuid.uuid4(),
                order_number=uuid.uuid4().hex[:20],
                encounter_id=encounters[0].id,
                facility_id=facility.id,
                patient_id=visit.patient_id,
                order_type="lab" if kind == "lab-result" else "radiology",
                ordered_at=now - timedelta(hours=1),
                created_by=doctor.id,
            )
            if kind == "lab-result":
                item = LabOrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    accession_number=uuid.uuid4().hex[:20],
                    test_name=f"Test {number}",
                    sample_type="blood",
                    created_by=doctor.id,
                )
                row = LabResult(
                    id=uuid.uuid4(),
                    lab_order_item_id=item.id,
                    result_data={"value": number},
                    version=1,
                    is_current=True,
                    status="final",
                    created_by=doctor.id,
                    created_at=now,
                    updated_at=now,
                )
            else:
                item = RadiologyOrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    accession_number=uuid.uuid4().hex[:20],
                    modality="xray",
                    scan_type=f"Scan {number}",
                    created_by=doctor.id,
                    pacs_study_uid=f"2.25.{uuid.uuid4().int}",
                )
                row = RadiologyReport(
                    id=uuid.uuid4(),
                    radiology_order_item_id=item.id,
                    findings=f"Findings {number}",
                    impression=f"Impression {number}",
                    version=1,
                    is_current=True,
                    status="final",
                    created_by=doctor.id,
                    created_at=now,
                    updated_at=now,
                )
            db.add_all([order, item, row])
            rows.append(row)
        results[kind] = rows
    await db.flush()

    def context(kind, source_id, hi_type):
        return AbdmCareContext(
            id=uuid.uuid4(),
            facility_id=facility.id,
            patient_id=visit.patient_id,
            visit_id=visit.id,
            reference=f"{kind}/{source_id}",
            hi_type=hi_type,
            display="Test document",
            document_at=now,
            created_by=doctor.id,
        )

    return facility, encounters, prescriptions, results, context


async def test_prescription_shares_only_its_items_not_other_prescriptions(db, documents):
    facility, _, prescriptions, _, context = documents
    selected = context("prescription", prescriptions[0].id, "Prescription")
    facts = await _clinical_facts(db, selected, facility=facility)
    assert [item["name"] for item in facts["medications"]] == ["Test medicine 0-0"]
    assert facts["diagnostic_reports"] == []
    assert facts["chief_complaints"] == []
    bundle = build_clinical_bundle(selected.hi_type, **facts)
    assert (
        len([e for e in bundle["entry"] if e["resource"]["resourceType"] == "MedicationRequest"])
        == 1
    )


async def test_prescription_added_after_closure_is_not_backdated(db, documents):
    facility, encounters, prescriptions, _, context = documents
    prescription = prescriptions[0]
    prescription.created_at = encounters[0].ended_at + timedelta(days=1)
    expected_authored_at = prescription.created_at
    await db.flush()
    selected = context("prescription", prescription.id, "Prescription")
    with pytest.raises(TransferError, match="date requires reconciliation"):
        await _clinical_facts(db, selected, facility=facility)
    selected.document_at = prescription.created_at
    facts = await _clinical_facts(db, selected, facility=facility)
    assert facts["authored_at"] == expected_authored_at


async def test_consultation_never_selects_the_last_encounter_of_the_visit(db, documents):
    facility, encounters, _, _, context = documents
    facts = await _clinical_facts(
        db, context("encounter", encounters[0].id, "OPConsultation"), facility=facility
    )
    assert facts["care_plan"] == "Plan: Plan 0"
    assert [item["text"] for item in facts["chief_complaints"]] == ["Complaint 0"]
    assert facts["medications"] == facts["diagnostic_reports"] == []
    assert facts["encounter"]["id"] == encounters[0].id


@pytest.mark.parametrize("kind", ["encounter", "lab-result", "radiology-report"])
async def test_cached_source_cannot_hide_a_later_reopen_or_amendment(db, documents, kind):
    facility, encounters, _, results, context = documents
    source = encounters[0] if kind == "encounter" else results[kind][0]
    selected = context(
        kind, source.id, "OPConsultation" if kind == "encounter" else "DiagnosticReport"
    )
    await _clinical_facts(db, selected, facility=facility)
    # Bypass ORM synchronization to represent an independent writer changing
    # the stored row while this worker still holds its old identity-map object.
    changes = {"ended_at": None} if kind == "encounter" else {"is_current": False}
    await db.execute(
        update(type(source))
        .where(type(source).id == source.id)
        .values(**changes)
        .execution_options(synchronize_session=False)
    )
    assert source.ended_at is not None if kind == "encounter" else source.is_current
    with pytest.raises(TransferError, match="No finalized document"):
        await _clinical_facts(db, selected, facility=facility)


@pytest.mark.parametrize("kind", ["lab-result", "radiology-report"])
async def test_diagnostic_report_shares_one_selected_version(db, documents, kind):
    facility, _, _, results, context = documents
    selected = context(kind, results[kind][0].id, "DiagnosticReport")
    facts = await _clinical_facts(db, selected, facility=facility)
    assert [item["id"] for item in facts["diagnostic_reports"]] == [results[kind][0].id]
    assert facts["medications"] == []
    bundle = build_clinical_bundle(selected.hi_type, **facts)
    assert (
        len([e for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport"])
        == 1
    )


@pytest.mark.parametrize("kind", ["lab-result", "radiology-report"])
@pytest.mark.parametrize("invalid_state", ["preliminary", "superseded"])
async def test_unreleased_or_superseded_reports_are_not_exportable(
    db, documents, kind, invalid_state
):
    facility, _, _, results, context = documents
    row = results[kind][0]
    if invalid_state == "preliminary":
        row.status = "preliminary"
    else:
        row.is_current = False
    await db.flush()
    with pytest.raises(TransferError, match="No finalized document"):
        await _clinical_facts(db, context(kind, row.id, "DiagnosticReport"), facility=facility)


@pytest.mark.parametrize(
    "kind,hi_type",
    [
        ("encounter", "OPConsultation"),
        ("prescription", "Prescription"),
        ("wellness", "WellnessRecord"),
    ],
)
async def test_open_consultation_cannot_be_exported_as_final(db, documents, kind, hi_type):
    facility, encounters, prescriptions, _, context = documents
    encounters[0].ended_at = None
    await db.flush()
    source_id = prescriptions[0].id if kind == "prescription" else encounters[0].id
    with pytest.raises(TransferError, match="No finalized document"):
        await _clinical_facts(db, context(kind, source_id, hi_type), facility=facility)


@pytest.mark.parametrize("wrong_field", ["patient_id", "facility_id", "visit_id"])
async def test_document_resolution_preserves_all_scope_boundaries(db, documents, wrong_field):
    facility, _, prescriptions, _, context = documents
    selected = context("prescription", prescriptions[0].id, "Prescription")
    scope = dict(
        patient_id=selected.patient_id, facility_id=facility.id, visit_id=selected.visit_id
    )
    scope[wrong_field] = uuid.uuid4()
    with pytest.raises(DocumentUnavailable):
        await resolve_document(db, reference=selected.reference, hi_type=selected.hi_type, **scope)


@pytest.mark.parametrize("corruption", ["legacy", "type", "missing_date", "changed_date"])
async def test_ambiguous_contexts_fail_closed(db, documents, corruption):
    facility, encounters, _, _, context = documents
    selected = context("encounter", encounters[0].id, "OPConsultation")
    if corruption == "legacy":
        selected.reference = f"visit/{selected.visit_id}"
    elif corruption == "type":
        selected.hi_type = "Prescription"
    elif corruption == "missing_date":
        selected.document_at = None
    else:
        selected.document_at -= timedelta(days=1)
    with pytest.raises(TransferError):
        await _clinical_facts(db, selected, facility=facility)


async def test_discovery_excludes_unreconciled_and_superseded_documents(db, documents):
    facility, encounters, _, results, context = documents
    valid = context("encounter", encounters[0].id, "OPConsultation")
    legacy = context("encounter", encounters[1].id, "OPConsultation")
    legacy.document_at = None
    superseded = context("lab-result", results["lab-result"][0].id, "DiagnosticReport")
    results["lab-result"][0].is_current = False
    db.add_all([valid, legacy, superseded])
    await db.flush()
    assert [
        row.id for row in await _contexts(db, facility_id=facility.id, patient_id=valid.patient_id)
    ] == [valid.id]


async def test_wellness_uses_only_selected_encounter_measurements_before_finalization(
    db, documents
):
    facility, encounters, _, _, context = documents
    selected = context("wellness", encounters[0].id, "WellnessRecord")
    for encounter, offset, pulse in [
        (encounters[0], -1, 70),
        (encounters[0], 1, 80),
        (encounters[1], -1, 90),
    ]:
        db.add(
            Vitals(
                id=uuid.uuid4(),
                patient_id=selected.patient_id,
                encounter_id=encounter.id,
                measured_at=selected.document_at + timedelta(minutes=offset),
                pulse_bpm=pulse,
                created_by=encounter.created_by,
            )
        )
    await db.flush()
    facts = await _clinical_facts(db, selected, facility=facility)
    assert [row["value"] for row in facts["observations"]] == [70]
    assert build_clinical_bundle(selected.hi_type, **facts)["type"] == "document"


async def test_discharge_uses_its_own_summary_without_requiring_an_opd_encounter(
    db, documents, nursing_seed, seed
):
    facility, _, _, _, context = documents
    _, _, doctor = seed
    discharge = Discharge(
        id=uuid.uuid4(),
        admission_id=nursing_seed["admission_id"],
        discharged_at=datetime.now(UTC),
        discharge_type="discharged",
        discharge_summary="Final discharge summary",
        created_by=doctor.id,
    )
    db.add(discharge)
    await db.flush()
    selected = context("discharge", discharge.id, "DischargeSummary")
    selected.patient_id = nursing_seed["patient_id"]
    selected.visit_id = nursing_seed["visit_id"]
    selected.document_at = discharge.discharged_at
    facts = await _clinical_facts(db, selected, facility=facility)
    assert facts["care_plan"] == discharge.discharge_summary
    assert facts["diagnoses"] == facts["medications"] == facts["diagnostic_reports"] == []
    assert build_clinical_bundle(selected.hi_type, **facts)["type"] == "document"
