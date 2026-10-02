"""A recorded vaccine dose is one shareable NRCeS ImmunizationRecord.

The dose belongs to no visit. Recording it offers a care context in the same
transaction; the resolver scopes it by the chart it was written on; the
transfer builds an ImmunizationRecord with no Encounter; and the HI-request
selection reaches it although there is no visit to join through.
"""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.immunization.schemas import ImmunizationRecordCreate
from app.immunization.service import ensure_catalogue_seeded, record_administration
from app.integrations.abdm.fhir.builder import build_clinical_bundle, validate_min
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hip.documents import (
    DocumentUnavailable,
    resolve_context_document,
    resolve_document,
)
from app.integrations.abdm.hip.models import AbdmCareContext, AbdmCareContextLink
from app.integrations.abdm.hip.router import CareContextIn, create_care_context
from app.integrations.abdm.hip.worker import TransferError, _clinical_facts
from app.integrations.abdm.jobs import AbdmJob
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio

ADDRESS = "immunized.child@sbx"


@pytest.fixture
async def chart(db):
    facility = Facility(
        id=uuid.uuid4(), code=f"IM{uuid.uuid4().hex[:4].upper()}", name="Immunization Test Facility",
        state_code="TS", hfr_facility_id="TEST-HFR",
    )
    nurse = User(
        id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"sub-{uuid.uuid4()}",
        username=f"nurse{uuid.uuid4().hex[:6]}", full_name="Nurse Test", is_active=True,
        registration_number="TEST-NURSE-REG",
    )
    db.add_all([facility, nurse])
    await db.flush()
    child = Patient(
        id=uuid.uuid4(), facility_id=facility.id, uhid=f"UH{uuid.uuid4().hex[:8]}",
        full_name="Test Child", sex="female", dob=date.today() - timedelta(days=60),
        identity_path="demographics_only", created_by=nurse.id,
    )
    db.add(child)
    await db.flush()
    await ensure_catalogue_seeded(db)
    return facility, nurse, child


@pytest.fixture
async def dose(db, chart):
    facility, nurse, child = chart
    recorded = await record_administration(
        db,
        ImmunizationRecordCreate(
            patient_id=child.id, vaccine_code="PENTAVALENT-1", dose_number=1,
            batch_number="TEST-BATCH-1", expiry_date=date.today() + timedelta(days=200),
            manufacturer="Test Manufacturer", route="intramuscular",
            site="anterolateral_thigh", adverse_reaction="Mild fever",
        ),
        nurse.id,
    )
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == child.id))
    ).scalar_one()
    return facility, nurse, child, recorded, context


async def test_recording_a_dose_offers_one_visitless_immunization_document(db, dose):
    facility, _nurse, child, recorded, context = dose
    assert context.reference == f"immunization/{recorded.id}"
    assert context.hi_type == "ImmunizationRecord"
    assert context.visit_id is None and context.facility_id == facility.id
    assert context.display.startswith("Immunization — ")
    assert context.display.endswith(" — PENTAVALENT-1 dose 1")
    source = await resolve_document(
        db, reference=context.reference, hi_type=context.hi_type,
        patient_id=child.id, facility_id=facility.id, visit_id=None,
    )
    assert source.visit is None and source.author_id == recorded.administered_by
    # The stored document date is exactly the source's, so it stays shareable.
    assert await resolve_context_document(db, context) == source
    job = (
        await db.execute(select(AbdmJob).where(AbdmJob.target_id == context.id))
    ).scalar_one()
    assert job.kind == "context_notify"


async def test_the_transfer_builds_an_immunization_record_without_an_encounter(db, dose):
    facility, _nurse, _child, recorded, context = dose
    facts = await _clinical_facts(db, context, facility=facility)
    bundle = build_clinical_bundle(context.hi_type, **facts)
    assert validate_min(bundle) == []
    kinds = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
    assert kinds == ["Composition", "Practitioner", "Organization", "Patient", "Immunization"]
    composition = bundle["entry"][0]["resource"]
    assert "encounter" not in composition
    assert composition["type"]["coding"][0]["code"] == "41000179103"
    assert [s["code"]["coding"][0]["code"] for s in composition["section"]] == ["41000179103"]
    immunization = bundle["entry"][-1]["resource"]
    vaccine = await db.get(VaccineCatalogue, recorded.vaccine_id)
    assert immunization["vaccineCode"] == {"text": vaccine.name}
    assert immunization["lotNumber"] == "TEST-BATCH-1"
    assert immunization["protocolApplied"] == [
        {"doseNumberPositiveInt": 1, "targetDisease": [{"text": vaccine.target_disease}]}
    ]
    assert immunization["route"] == {"text": "intramuscular"}
    assert immunization["site"] == {"text": "anterolateral thigh"}
    assert immunization["manufacturer"] == {"display": "Test Manufacturer"}
    assert immunization["note"] == [{"text": "Adverse reaction: Mild fever"}]
    performer = immunization["performer"][0]["actor"]["reference"]
    assert performer == f"urn:uuid:{bundle['entry'][1]['resource']['id']}"


@pytest.mark.parametrize("change", ["patient", "facility", "visit"])
async def test_a_dose_is_not_shareable_outside_the_chart_it_was_written_on(
    db, dose, opd_visit, change
):
    facility, _nurse, child, _recorded, context = dose
    patient_id, facility_id, visit_id = child.id, facility.id, None
    if change == "patient":
        patient_id = (await opd_visit()).patient_id
    elif change == "facility":
        facility_id = uuid.uuid4()
    else:
        visit_id = (await opd_visit()).id
    with pytest.raises(DocumentUnavailable):
        await resolve_document(
            db, reference=context.reference, hi_type="ImmunizationRecord",
            patient_id=patient_id, facility_id=facility_id, visit_id=visit_id,
        )


async def test_an_administrator_without_a_registration_cannot_author_the_document(db, dose):
    facility, nurse, _child, _recorded, context = dose
    nurse.registration_number = None
    await db.flush()
    with pytest.raises(TransferError, match="registration number"):
        await _clinical_facts(db, context, facility=facility)


def _authorisation(*references):
    artefact = SimpleNamespace(raw_artefact={"notification": {"consentDetail": {
        "careContexts": [{"careContextReference": r} for r in references]}}})
    return hip_service.Authorisation(
        artefact=artefact, hi_types=["ImmunizationRecord", "OPConsultation"],
        date_range_from=None, date_range_to=None,
    )


async def test_a_consented_immunization_is_selected_for_transfer_without_a_visit(db, dose):
    facility, _nurse, child, _recorded, context = dose
    stray = AbdmCareContext(
        id=uuid.uuid4(), facility_id=facility.id, patient_id=child.id, visit_id=None,
        reference=f"encounter/{uuid.uuid4()}", display="Visitless consultation",
        hi_type="OPConsultation", document_at=context.document_at, created_by=_nurse.id,
    )
    db.add(stray)
    db.add(AbdmCareContextLink(
        id=uuid.uuid4(), facility_id=facility.id, patient_id=child.id, abha_address=ADDRESS,
        status="confirmed", care_context_references=[context.reference, stray.reference],
    ))
    await db.flush()
    selected = await hip_service.list_care_contexts_for_transfer(
        db, facility_id=facility.id, abha_address=ADDRESS,
        authorisation=_authorisation(context.reference, stray.reference),
    )
    # Only an immunization may stand without a visit; any other type still
    # has to sit in this patient's visit at this facility.
    assert [row.id for row in selected] == [context.id]


async def test_a_dose_recorded_before_publishing_existed_can_be_registered_by_hand(db, chart):
    facility, nurse, child = chart
    vaccine = (
        await db.execute(select(VaccineCatalogue).where(VaccineCatalogue.code == "BCG"))
    ).scalar_one()
    earlier = ImmunizationRecord(
        id=uuid.uuid4(), patient_id=child.id, vaccine_id=vaccine.id, vaccine_code=vaccine.code,
        dose_number=1, batch_number="OLD-BATCH", expiry_date=date.today() + timedelta(days=30),
        administered_by=nurse.id,
    )
    db.add(earlier)
    await db.flush()
    await db.refresh(earlier)
    payload = CareContextIn(
        patient_id=child.id, reference=f"immunization/{earlier.id}",
        display="Immunization BCG dose 1", hi_type="ImmunizationRecord",
    )
    created = await create_care_context(
        payload, current_db_user=nurse, idempotency_key="imm-manual-1", db=db
    )
    context = await db.get(AbdmCareContext, created.id)
    assert context.visit_id is None and context.reference == payload.reference
    assert context.document_at is not None
