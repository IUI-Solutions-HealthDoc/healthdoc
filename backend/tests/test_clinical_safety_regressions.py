"""Negative ownership, issue-safety and evidence-derived reporting regressions."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, func

from app.auth.deps import AuthUser, DbUser, get_current_user, get_current_db_user
from app.common.db import get_db
from app.blood_bank import service as blood
from app.blood_bank.models import BloodUnit, BloodCrossmatch
from app.blood_bank.schemas import BloodDonorCreate, BloodUnitCreate, BloodCrossmatchCreate, BloodIssueRequest
from app.forms.router import router as forms_router
from app.forms.service import import_csv, validate_csv
from app.immunization.router import router as immunization_router
from app.immunization.models import ImmunizationRecord
from app.opd.models import Visit, Encounter
from app.patients.models import PatientPortalBinding
from app.reports.service import produce_kpi_snapshots, get_receptionist_summary
from app.reports.models import KpiSnapshot, TIMING_KPI_VERSION
from app.reports.router import list_kpis, list_kpi_codes
from app.audit.models import AuditLog
from app.orders.models import Order, Prescription
from app.ot.schemas import OtScheduleCreate
from app.ot.service import create_ot_schedule
from app.pathology.models import LabOrderItem, LabResult
from app.pharmacy.models import PharmacyDispense, PharmacyReturn
from app.pharmacy.schemas import PharmacyReturnCreate
from app.pharmacy.service import create_pharmacy_return
from app.programs.schemas import ProgramEnrolmentCreate
from app.programs.service import enrol_patient
from app.radiology.models import RadiologyOrderItem
from app.radiology.router import upload_order_attachment
from app.terminology.router import router as specialty_router
from app.terminology.models import SpecialtyEncounter
from tests.test_suite_8_immunization_blood_forms import _setup_suite_8_fixture

pytestmark = pytest.mark.asyncio


def actor(facility, staff, roles):
    return DbUser(id=staff.id, keycloak_sub=staff.keycloak_sub, username=staff.username,
                  facility_id=facility.id, roles=roles)


async def client_for(db, caller):
    app = FastAPI()
    app.include_router(forms_router)
    app.include_router(immunization_router)
    app.include_router(specialty_router)
    async def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub=caller.keycloak_sub, roles=caller.roles)
    app.dependency_overrides[get_current_db_user] = lambda: caller
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
        headers={"Idempotency-Key": str(uuid.uuid4())})


@pytest.mark.parametrize("path", ["/forms/patients/{id}", "/immunization/patients/{id}", "/immunization/patients/{id}/certificate"])
async def test_patient_cannot_read_another_patient_or_use_revoked_binding(db, path):
    facility, staff, child, adult = await _setup_suite_8_fixture(db)
    binding = PatientPortalBinding(id=uuid.uuid4(), user_id=staff.id, patient_id=child.id,
        facility_id=facility.id, verification_method="in_person_document",
        verification_reference="test-verification", verified_by=staff.id)
    db.add(binding)
    await db.flush()
    async with await client_for(db, actor(facility, staff, ["patient"])) as client:
        assert (await client.get(path.format(id=adult.id))).status_code == 404
        assert (await client.get(path.format(id=child.id))).status_code == 200
        binding.revoked_at = datetime.now(timezone.utc)
        binding.revoked_by = staff.id
        binding.revocation_reason = "Regression test revocation"
        await db.flush()
        assert (await client.get(path.format(id=child.id))).status_code == 404


async def test_foreign_patient_and_mismatched_visit_rejected_before_writes(db):
    facility, staff, child, adult = await _setup_suite_8_fixture(db)
    other, _, foreign, _ = await _setup_suite_8_fixture(db)
    visit = Visit(id=uuid.uuid4(), visit_number="SCOPE-VISIT", facility_id=facility.id,
        patient_id=adult.id, visit_type="opd", status="registered", created_by=staff.id,
        visit_date=datetime.now(timezone.utc))
    db.add(visit)
    await db.flush()
    async with await client_for(db, actor(facility, staff, ["nurse"])) as client:
        assert (await client.get(f"/immunization/patients/{foreign.id}")).status_code == 404
        assert (await client.post("/immunization/records", json={
            "patient_id": str(foreign.id), "vaccine_code": "BCG", "batch_number": "TEST",
            "expiry_date": "2099-01-01"})).status_code == 404
        response = await client.post("/forms/submissions", json={
            "patient_id": str(child.id), "visit_id": str(visit.id),
            "form_id": str(uuid.uuid4()), "form_data": {}})
        assert response.status_code == 404
    assert (await db.execute(select(func.count(ImmunizationRecord.id)))).scalar_one() == 0


async def prepared_blood(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)
    donor = await blood.create_donor(db, BloodDonorCreate(full_name="Test Donor",
        blood_group="O+", weight_kg=65, hemoglobin_g_dl=14), staff.id)
    unit = await blood.create_unit(db, BloodUnitCreate(donor_id=donor.id,
        bag_number="BAG-" + uuid.uuid4().hex[:10], blood_group="O+",
        expiry_date=date.today() + timedelta(days=7), screening_status="passed"), staff.id)
    xm = await blood.create_crossmatch(db, BloodCrossmatchCreate(patient_id=adult.id,
        unit_id=unit.id, compatibility_result="compatible"), staff.id)
    return facility, staff, adult, unit, xm


@pytest.mark.parametrize("state,screening,expired", [
    ("available", "passed", True), ("available", "failed", False),
    ("available", "pending", False), ("quarantined", "passed", False),
    ("discarded", "passed", False), ("reserved", "passed", False),
])
async def test_issue_rechecks_current_expiry_screening_and_state(db, state, screening, expired):
    _, staff, _, unit, xm = await prepared_blood(db)
    stored = await db.get(BloodUnit, unit.id)
    stored.status, stored.screening_status = state, screening
    if expired:
        stored.expiry_date = date.today() - timedelta(days=2)
    await db.flush()
    with pytest.raises(ValueError):
        await blood.issue_blood(db, BloodIssueRequest(crossmatch_id=xm.id), staff.id)
    assert (await db.get(BloodCrossmatch, xm.id)).issued_at is None
    assert stored.issued_to_patient_id is None


async def test_blood_is_facility_scoped_and_patient_checked(db):
    _, staff, _, unit, xm = await prepared_blood(db)
    other, outsider, foreign, _ = await _setup_suite_8_fixture(db)
    assert await blood.list_units(db, other.id) == []
    assert await blood.list_donors(db, other.id) == []
    with pytest.raises(ValueError, match="not found"):
        await blood.issue_blood(db, BloodIssueRequest(crossmatch_id=xm.id), outsider.id)
    with pytest.raises(HTTPException) as exc:
        await blood.create_crossmatch(db, BloodCrossmatchCreate(patient_id=foreign.id,
            unit_id=unit.id, compatibility_result="compatible"), staff.id)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("entity", ["forms", "inventory", "order_sets", "unknown"])
async def test_unsupported_csv_cannot_claim_success(db, entity):
    assert not validate_csv("code,name\nX,Y", entity).valid
    with pytest.raises(ValueError):
        await import_csv("code,name\nX,Y", entity, db, uuid.uuid4())


async def test_wait_times_come_from_actual_encounters_not_constants(db):
    facility, staff, _, adult = await _setup_suite_8_fixture(db)
    day = date(2026, 1, 12)
    for wait in (12, 30):
        arrival = datetime(2026, 1, 12, 8, tzinfo=timezone.utc)
        visit = Visit(id=uuid.uuid4(), visit_number=uuid.uuid4().hex[:20], facility_id=facility.id,
            patient_id=adult.id, visit_type="opd", status="completed", visit_date=arrival, created_by=staff.id)
        db.add(visit)
        db.add(Encounter(id=uuid.uuid4(), visit_id=visit.id, facility_id=facility.id,
            provider_user_id=staff.id, started_at=arrival+timedelta(minutes=wait), created_by=staff.id))
    await db.flush()
    snapshots = await produce_kpi_snapshots(db, facility.id, day, day,
        ["OPD_AVG_WAIT_MINS", "LAB_TURNAROUND_HOURS"])
    assert len(snapshots) == 1  # no laboratory observations => no fabricated snapshot
    assert snapshots[0].value == Decimal(21)
    assert snapshots[0].denominator == 2
    summary = await get_receptionist_summary(db, facility.id, day)
    assert summary.average_wait_minutes == 21
    assert snapshots[0].calculation_version == TIMING_KPI_VERSION
    published = await list_kpis(actor(facility, staff, ["admin"]), period="daily",
        date_from=day, date_to=day, db=db)
    assert [item.value for item in published.items] == [Decimal(21)]


async def test_lab_tat_uses_first_verify_audit_not_later_amendment(db):
    facility, staff, _, patient = await _setup_suite_8_fixture(db)
    collected = datetime(2026, 1, 12, 8, tzinfo=timezone.utc)
    visit = Visit(id=uuid.uuid4(), visit_number=uuid.uuid4().hex[:20], facility_id=facility.id,
        patient_id=patient.id, visit_type="opd", visit_date=collected, created_by=staff.id)
    encounter = Encounter(id=uuid.uuid4(), visit_id=visit.id, facility_id=facility.id,
        provider_user_id=staff.id, started_at=collected, created_by=staff.id)
    order = Order(id=uuid.uuid4(), order_number=uuid.uuid4().hex[:20], encounter_id=encounter.id,
        patient_id=patient.id, facility_id=facility.id, order_type="lab", ordered_at=collected,
        created_by=staff.id)
    item = LabOrderItem(id=uuid.uuid4(), order_id=order.id, accession_number=uuid.uuid4().hex[:20],
        test_name="Test analyte", sample_type="blood", collected_at=collected, created_by=staff.id)
    result = LabResult(id=uuid.uuid4(), lab_order_item_id=item.id, version=1, is_current=True,
        result_data={}, status="final", created_by=staff.id,
        updated_at=collected + timedelta(days=2))
    db.add_all([visit, encounter, order, item, result])
    for hours in (2, 4):
        db.add(AuditLog(id=uuid.uuid4(), facility_id=facility.id, user_id=staff.id,
            action="verify", resource_type="lab_results", resource_id=result.id,
            created_at=collected + timedelta(hours=hours)))
    await db.flush()
    snapshots = await produce_kpi_snapshots(db, facility.id, date(2026, 1, 12),
        date(2026, 1, 12), ["LAB_TURNAROUND_HOURS"])
    assert len(snapshots) == 1
    assert snapshots[0].value == Decimal(2)
    assert snapshots[0].denominator == 1


@pytest.mark.parametrize("previously_verified", [False, True])
async def test_unverified_or_now_unmeasurable_timing_snapshots_are_retained_but_not_published(db, previously_verified):
    facility, staff, _, _ = await _setup_suite_8_fixture(db)
    day = date(2026, 1, 12)
    for code in ("OPD_AVG_WAIT_MINS", "LAB_TURNAROUND_HOURS"):
        db.add(KpiSnapshot(id=uuid.uuid4(), facility_id=facility.id, kpi_code=code,
            period_start=day, period_end=day, value=Decimal("14.5"),
            calculation_version=TIMING_KPI_VERSION if previously_verified else None))
    await db.flush()
    if previously_verified:
        # If source observations disappear, recalculation must invalidate the
        # old measurement rather than leave a stale value looking current.
        assert await produce_kpi_snapshots(db, facility.id, day, day,
            ["OPD_AVG_WAIT_MINS", "LAB_TURNAROUND_HOURS"]) == []
    published = await list_kpis(actor(facility, staff, ["admin"]), period="daily",
        date_from=day, date_to=day, db=db)
    assert published.no_snapshots is True
    assert published.items == []
    assert (await list_kpi_codes(actor(facility, staff, ["admin"]), db=db))["items"] == []
    assert (await db.execute(select(func.count(KpiSnapshot.id)))).scalar_one() == 2


@pytest.mark.parametrize("module", ["ot", "programs", "returns"])
async def test_new_clinical_writes_reject_foreign_patient(db, module):
    facility, staff, _, _ = await _setup_suite_8_fixture(db)
    _, _, foreign, _ = await _setup_suite_8_fixture(db)
    with pytest.raises(HTTPException) as exc:
        if module == "ot":
            start = datetime.now(timezone.utc)
            await create_ot_schedule(db, facility.id, OtScheduleCreate(patient_id=foreign.id,
                visit_id=uuid.uuid4(), scheduled_start=start, scheduled_end=start+timedelta(hours=1),
                procedure_name="Test procedure"), staff.id)
        elif module == "programs":
            await enrol_patient(db, facility.id, ProgramEnrolmentCreate(patient_id=foreign.id,
                program_code="DIABETES_T2"), staff.id)
        else:
            await create_pharmacy_return(db, facility_id=facility.id, user_id=staff.id, payload=PharmacyReturnCreate(
                patient_id=foreign.id, item_id=uuid.uuid4(), quantity=1,
                return_reason="Test", disposition="quarantine"))
    assert exc.value.status_code == 404


async def test_return_rejects_another_patients_dispense_before_inventory_mutation(db):
    facility, staff, child, adult = await _setup_suite_8_fixture(db)
    prescription = Prescription(id=uuid.uuid4(), encounter_id=uuid.uuid4(),
        facility_id=facility.id, patient_id=adult.id, created_by=staff.id)
    dispense = PharmacyDispense(id=uuid.uuid4(), prescription_id=prescription.id,
        dispensed_by=staff.id)
    db.add_all([prescription, dispense])
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await create_pharmacy_return(db, facility_id=facility.id, user_id=staff.id, payload=PharmacyReturnCreate(
            patient_id=child.id, dispense_id=dispense.id, item_id=uuid.uuid4(), quantity=1,
            return_reason="Test", disposition="quarantine"))
    assert exc.value.status_code == 404
    assert (await db.execute(select(func.count(PharmacyReturn.id)))).scalar_one() == 0


async def test_attachment_rejects_another_orders_item_before_reading_upload(db):
    facility, staff, _, patient = await _setup_suite_8_fixture(db)
    order = Order(id=uuid.uuid4(), order_number=uuid.uuid4().hex[:20], encounter_id=uuid.uuid4(),
        patient_id=patient.id, facility_id=facility.id, order_type="radiology",
        ordered_at=datetime.now(timezone.utc), created_by=staff.id)
    unrelated = RadiologyOrderItem(id=uuid.uuid4(), order_id=uuid.uuid4(),
        accession_number=uuid.uuid4().hex[:20], modality="xray", scan_type="Chest", created_by=staff.id)
    db.add_all([order, unrelated])
    await db.flush()
    class UnreadableUpload:
        async def read(self, size=-1):
            pytest.fail("an unrelated item's upload must not be read or stored")
    with pytest.raises(HTTPException) as exc:
        await upload_order_attachment(current_db_user=actor(facility, staff, ["doctor"]),
            order_id=order.id, file=UnreadableUpload(), radiology_order_item_id=unrelated.id, db=db)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("roles", [["patient"], ["receptionist"], ["billing"], ["auditor"]])
async def test_specialty_assessment_refuses_nonclinical_accounts_for_read_and_write(db, roles):
    facility, staff, _, _ = await _setup_suite_8_fixture(db)
    async with await client_for(db, actor(facility, staff, roles)) as client:
        path = f"/clinical/encounters/{uuid.uuid4()}/specialty"
        assert (await client.get(path)).status_code == 403
        assert (await client.post(path, json={"specialty_type": "cardiology", "clinical_data": {}})).status_code == 403
    assert (await db.execute(select(func.count(SpecialtyEncounter.id)))).scalar_one() == 0


async def test_specialty_assessment_refuses_foreign_and_mixed_role_patient_access(db):
    facility, staff, _, patient = await _setup_suite_8_fixture(db)
    other, outsider, _, _ = await _setup_suite_8_fixture(db)
    visit = Visit(id=uuid.uuid4(), visit_number=uuid.uuid4().hex[:20], facility_id=facility.id,
        patient_id=patient.id, visit_type="opd", visit_date=datetime.now(timezone.utc), created_by=staff.id)
    encounter = Encounter(id=uuid.uuid4(), visit_id=visit.id, facility_id=facility.id,
        provider_user_id=staff.id, created_by=staff.id)
    db.add_all([visit, encounter])
    await db.flush()
    for caller in (actor(other, outsider, ["doctor"]), actor(facility, staff, ["doctor", "patient"])):
        async with await client_for(db, caller) as client:
            path = f"/clinical/encounters/{encounter.id}/specialty"
            assert (await client.get(path)).status_code == 404
            assert (await client.post(path, json={"specialty_type": "cardiology", "clinical_data": {}})).status_code == 404
