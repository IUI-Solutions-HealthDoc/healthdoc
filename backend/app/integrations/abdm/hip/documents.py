"""Resolve one finalized source document; never infer it from an entire visit.

Canonical references are stable source-kind/UUID pairs. The source graph is
checked against both patient and facility before it is usable for sharing.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Discharge
from app.integrations.abdm.hip.models import AbdmCareContext
from app.opd.models import Encounter, Visit
from app.orders.models import Order, Prescription
from app.pathology.models import LabOrderItem, LabResult
from app.radiology.models import RadiologyOrderItem, RadiologyReport

SOURCE_TYPES = {
    "encounter": "OPConsultation",
    "prescription": "Prescription",
    "lab-result": "DiagnosticReport",
    "radiology-report": "DiagnosticReport",
    "discharge": "DischargeSummary",
    "wellness": "WellnessRecord",
}


class DocumentUnavailable(ValueError):
    """The source is absent, outside the requested scope, or not finalized."""


@dataclass(frozen=True)
class DocumentSource:
    kind: str
    source_id: uuid.UUID
    visit: Visit
    encounter: Encounter | None
    authored_at: datetime
    author_id: uuid.UUID


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _fresh(db: AsyncSession, model, ident):
    # Worker sessions survive multiple pages: cached final/current flags must
    # not conceal an intervening amendment or patient/source reassignment.
    return await db.get(model, ident, populate_existing=True)


async def resolve_document(
    db: AsyncSession,
    *,
    reference: str,
    hi_type: str,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    visit_id: uuid.UUID | None,
) -> DocumentSource:
    try:
        kind, raw_id = reference.split("/", 1)
        source_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError) as exc:
        raise DocumentUnavailable("A canonical finalized-document reference is required") from exc
    if SOURCE_TYPES.get(kind) != hi_type or reference != f"{kind}/{source_id}":
        raise DocumentUnavailable("Document reference and health-information type do not match")

    encounter = None
    visit = None
    authored_at = None
    author_id = None
    if kind in {"encounter", "wellness"}:
        encounter = await _fresh(db, Encounter, source_id)
        if encounter is not None:
            authored_at, author_id = encounter.ended_at, encounter.provider_user_id
    elif kind == "prescription":
        prescription = await _fresh(db, Prescription, source_id)
        if prescription is not None and (
            prescription.patient_id == patient_id and prescription.facility_id == facility_id
        ):
            encounter = await _fresh(db, Encounter, prescription.encounter_id)
            if encounter is not None and encounter.ended_at is not None:
                # This schema has no prescription sign-off field. Do not treat
                # a saved draft in an open consultation as a finalized record.
                # A prescription entered after closure did not exist when
                # the consultation ended; never backdate it into that window.
                authored_at = max(_utc(encounter.ended_at), _utc(prescription.created_at))
                author_id = prescription.created_by
    elif kind in {"lab-result", "radiology-report"}:
        model = LabResult if kind == "lab-result" else RadiologyReport
        result = await _fresh(db, model, source_id)
        if result is not None and result.status in {"final", "corrected"} and result.is_current:
            item = await _fresh(
                db,
                LabOrderItem if kind == "lab-result" else RadiologyOrderItem,
                result.lab_order_item_id
                if kind == "lab-result"
                else result.radiology_order_item_id,
            )
            order = await _fresh(db, Order, item.order_id) if item else None
            if (
                order is not None
                and order.patient_id == patient_id
                and order.facility_id == facility_id
            ):
                encounter = await _fresh(db, Encounter, order.encounter_id)
                authored_at = result.updated_at if kind == "lab-result" else result.created_at
                author_id = result.created_by
    elif kind == "discharge":
        discharge = await _fresh(db, Discharge, source_id)
        admission = await _fresh(db, Admission, discharge.admission_id) if discharge else None
        if (
            admission is not None
            and admission.patient_id == patient_id
            and discharge.discharge_summary
        ):
            visit = await _fresh(db, Visit, admission.visit_id)
            authored_at, author_id = discharge.discharged_at, discharge.created_by

    if encounter is not None:
        if encounter.facility_id != facility_id:
            raise DocumentUnavailable("No finalized document for this patient and facility")
        visit = await _fresh(db, Visit, encounter.visit_id)
    if (
        visit is None
        or visit.patient_id != patient_id
        or visit.facility_id != facility_id
        or (visit_id is not None and visit.id != visit_id)
        or authored_at is None
        or author_id is None
    ):
        raise DocumentUnavailable("No finalized document for this patient and facility")
    return DocumentSource(
        kind,
        source_id,
        visit,
        encounter,
        _utc(authored_at),
        author_id,
    )


async def resolve_context_document(db: AsyncSession, context: AbdmCareContext) -> DocumentSource:
    source = await resolve_document(
        db,
        reference=context.reference,
        hi_type=context.hi_type,
        patient_id=context.patient_id,
        facility_id=context.facility_id,
        visit_id=context.visit_id,
    )
    document_at = context.document_at
    if document_at is not None and document_at.tzinfo is None:
        document_at = document_at.replace(tzinfo=UTC)
    if document_at != source.authored_at:
        raise DocumentUnavailable("Document date requires reconciliation before sharing")
    return source
