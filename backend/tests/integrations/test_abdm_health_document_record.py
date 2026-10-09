"""A released PDF is one shareable NRCeS HealthDocumentRecord.

Uploading a file to a chart shares nothing; a doctor's release does, in the
same transaction that records it. The document belongs to no visit, the
facility authors it, and the transfer embeds exactly the uploaded bytes:
a file whose stored object no longer matches its upload hash is refused, and
erasing the file withdraws the document.
"""

import base64
import hashlib
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.files import service as files_service
from app.files.models import FileRecord
from app.integrations.abdm.fhir.builder import build_clinical_bundle, validate_min
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_context_document
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmReleasedDocument,
)
from app.integrations.abdm.hip.router import (
    ReleaseDocumentIn,
    list_released_documents,
    release_document,
)
from app.integrations.abdm.hip.worker import TransferError, _clinical_facts
from app.integrations.abdm.jobs import AbdmJob
from app.patients.models import Patient
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
async def chart(db):
    facility = Facility(
        id=uuid.uuid4(), code=f"HD{uuid.uuid4().hex[:4].upper()}", name="Document Test Facility",
        state_code="TS", hfr_facility_id="TEST-HFR",
    )
    doctor = User(
        id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"sub-{uuid.uuid4()}",
        username=f"doc{uuid.uuid4().hex[:6]}", full_name="Doctor Test", is_active=True,
    )
    db.add_all([facility, doctor])
    await db.flush()
    patient = Patient(
        id=uuid.uuid4(), facility_id=facility.id, uhid=f"UH{uuid.uuid4().hex[:8]}",
        full_name="Test Patient", sex="male", dob=date(2000, 1, 1),
        identity_path="demographics_only", created_by=doctor.id,
    )
    db.add(patient)
    await db.flush()
    return facility, doctor, patient


async def _file(db, chart, *, content=PDF, content_type="application/pdf", patient_id=None):
    facility, doctor, patient = chart
    record = FileRecord(
        id=uuid.uuid4(), bucket="test", object_key=f"{uuid.uuid4()}.pdf",
        original_name="history.pdf", content_type=content_type, size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(), owner_module="patients",
        facility_id=facility.id, patient_id=patient_id or patient.id, uploaded_by=doctor.id,
        sensitivity="sensitive",
    )
    db.add(record)
    await db.flush()
    return record


def _release(file_id, *, title="Medical history form", on=None):
    return ReleaseDocumentIn(file_id=file_id, title=title, document_date=on or date.today())


async def _released(db, chart):
    _facility, doctor, patient = chart
    file = await _file(db, chart)
    out = await release_document(
        patient.id, _release(file.id), current_db_user=doctor, idempotency_key="rel-1", db=db
    )
    return file, out


async def test_releasing_a_pdf_offers_one_visitless_health_document(db, chart):
    facility, _doctor, patient = chart
    _file_row, out = await _released(db, chart)
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == patient.id))
    ).scalar_one()
    assert context.reference == f"document/{out.id}" == out.care_context_reference
    assert context.hi_type == "HealthDocumentRecord"
    assert context.visit_id is None and context.facility_id == facility.id
    assert context.display.startswith("Document — ") and len(context.display) <= 50
    jobs = (await db.execute(select(AbdmJob).where(AbdmJob.target_id == context.id))).scalars().all()
    assert [job.kind for job in jobs] == ["context_notify"]


async def test_a_retry_with_the_same_key_replays_and_a_second_release_is_refused(db, chart):
    _facility, doctor, patient = chart
    file, first = await _released(db, chart)
    again = await release_document(
        patient.id, _release(file.id), current_db_user=doctor, idempotency_key="rel-1", db=db
    )
    assert again == first
    with pytest.raises(HTTPException) as refused:
        await release_document(
            patient.id, _release(file.id), current_db_user=doctor, idempotency_key="rel-2", db=db
        )
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "document_already_released"


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("other_chart", 404, "file_not_found"),
        ("image", 422, "document_not_pdf"),
        ("too_large", 422, "document_too_large"),
        ("erased", 422, "file_erased"),
        ("future", 422, "document_date_in_future"),
    ],
)
async def test_a_release_is_refused_before_anything_is_offered(db, chart, case, status, code):
    _facility, doctor, patient = chart
    on = date.today()
    if case == "other_chart":
        other = Patient(
            id=uuid.uuid4(), facility_id=patient.facility_id, uhid=f"UH{uuid.uuid4().hex[:8]}",
            full_name="Other Patient", sex="female", dob=date(1990, 1, 1),
            identity_path="demographics_only", created_by=doctor.id,
        )
        db.add(other)
        await db.flush()
        file = await _file(db, chart, patient_id=other.id)
    elif case == "image":
        file = await _file(db, chart, content=b"\xff\xd8\xff\xe0jpeg", content_type="image/jpeg")
    elif case == "too_large":
        file = await _file(db, chart, content=b"%PDF-" + b"0" * (1024 * 1024))
    elif case == "erased":
        file = await _file(db, chart)
        file.erased_at, file.erased_by, file.erasure_reason = file.created_at, doctor.id, "test"
        file.object_key = file.sha256 = None
        await db.flush()
    else:
        file = await _file(db, chart)
        on = date.today() + timedelta(days=2)
    with pytest.raises(HTTPException) as refused:
        await release_document(
            patient.id, _release(file.id, on=on), current_db_user=doctor,
            idempotency_key=f"rel-{case}", db=db,
        )
    assert refused.value.status_code == status
    assert refused.value.detail["code"] == code
    assert (await db.execute(select(AbdmReleasedDocument))).scalars().all() == []
    assert (await db.execute(select(AbdmCareContext))).scalars().all() == []


async def test_the_transfer_embeds_the_uploaded_bytes_authored_by_the_facility(
    db, chart, monkeypatch
):
    facility, _doctor, patient = chart
    file, out = await _released(db, chart)

    async def _read(record, *, max_bytes):
        assert record.id == file.id and max_bytes == 1024 * 1024
        return PDF

    monkeypatch.setattr(files_service, "read_file_bytes", _read)
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == patient.id))
    ).scalar_one()
    facts = await _clinical_facts(db, context, facility=await db.get(Facility, facility.id))
    assert facts["practitioner"] is None and facts["encounter"] is None
    bundle = build_clinical_bundle("HealthDocumentRecord", **facts)
    assert validate_min(bundle) == []
    resources = {entry["resource"]["resourceType"]: entry["resource"] for entry in bundle["entry"]}
    composition, reference = resources["Composition"], resources["DocumentReference"]
    assert composition["type"]["coding"][0]["code"] == "419891008"
    assert composition["author"][0]["reference"] == f"urn:uuid:{resources['Organization']['id']}"
    assert "Practitioner" not in resources and "Encounter" not in resources
    attachment = reference["content"][0]["attachment"]
    assert base64.b64decode(attachment["data"]) == PDF
    assert attachment["size"] == len(PDF)
    assert attachment["title"] == out.title


async def test_a_consented_document_is_selected_for_transfer_without_a_visit(db, chart):
    # Live run 9 Oct: a consent covering a discharge summary and a released
    # document delivered only the discharge summary, because the selection let
    # only an immunization stand without a visit.
    facility, doctor, patient = chart
    await _released(db, chart)
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == patient.id))
    ).scalar_one()
    stray = AbdmCareContext(
        id=uuid.uuid4(), facility_id=facility.id, patient_id=patient.id, visit_id=None,
        reference=f"encounter/{uuid.uuid4()}", display="Visitless consultation",
        hi_type="OPConsultation", document_at=context.document_at, created_by=doctor.id,
    )
    db.add(stray)
    address = "document.holder@sbx"
    db.add(AbdmCareContextLink(
        id=uuid.uuid4(), facility_id=facility.id, patient_id=patient.id, abha_address=address,
        status="confirmed", care_context_references=[context.reference, stray.reference],
    ))
    await db.flush()
    artefact = SimpleNamespace(raw_artefact={"notification": {"consentDetail": {
        "careContexts": [{"careContextReference": r} for r in (context.reference, stray.reference)]
    }}})
    selected = await hip_service.list_care_contexts_for_transfer(
        db, facility_id=facility.id, abha_address=address,
        authorisation=hip_service.Authorisation(
            artefact=artefact, hi_types=["HealthDocumentRecord", "OPConsultation"],
            date_range_from=None, date_range_to=None,
        ),
    )
    # A consultation still has to sit in this patient's visit at this facility.
    assert [row.id for row in selected] == [context.id]


async def test_a_changed_stored_object_is_refused_not_shared(db, chart, monkeypatch):
    facility, _doctor, patient = chart
    await _released(db, chart)

    class _Object:
        def read(self, _n):
            return PDF + b"tampered"

        def close(self):
            pass

        def release_conn(self):
            pass

    class _Minio:
        def get_object(self, _bucket, _key):
            return _Object()

    monkeypatch.setattr(files_service, "get_minio_client", lambda: _Minio())
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == patient.id))
    ).scalar_one()
    with pytest.raises(TransferError, match="no longer matches"):
        await _clinical_facts(db, context, facility=await db.get(Facility, facility.id))


async def test_erasing_the_file_withdraws_the_document(db, chart):
    _facility, doctor, patient = chart
    file, _out = await _released(db, chart)
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.patient_id == patient.id))
    ).scalar_one()
    await resolve_context_document(db, context)
    file.erased_at, file.erased_by, file.erasure_reason = file.created_at, doctor.id, "withdrawn"
    file.object_key = file.sha256 = None
    await db.flush()
    with pytest.raises(DocumentUnavailable):
        await resolve_context_document(db, context)


async def test_the_desk_lists_released_documents_for_this_chart_only(db, chart):
    _facility, doctor, patient = chart
    _file_row, out = await _released(db, chart)
    listed = await list_released_documents(patient.id, current_db_user=doctor, db=db)
    assert [row.id for row in listed] == [out.id]
    with pytest.raises(HTTPException) as missing:
        await list_released_documents(uuid.uuid4(), current_db_user=doctor, db=db)
    assert missing.value.status_code == 404
