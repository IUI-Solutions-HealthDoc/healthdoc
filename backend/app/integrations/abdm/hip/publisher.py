"""Clinical completion → scoped document registry, atomically and without HTTP."""

import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Invoice
from app.common.patient_scope import facility_timezone
from app.immunization.models import ImmunizationRecord, VaccineCatalogue
from app.integrations.abdm.hip.documents import (
    SOURCE_TYPES,
    DocumentSource,
    DocumentUnavailable,
    resolve_document,
)
from app.integrations.abdm.hip.models import AbdmCareContext, AbdmReleasedDocument
from app.integrations.abdm.jobs import enqueue
from app.nursing.models import Vitals
from app.opd.models import Encounter, Visit
from app.orders.models import Order, Prescription
from app.patients.models import Patient


async def _publish(
    db: AsyncSession,
    *,
    kind: str,
    source_id: uuid.UUID,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    visit_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    display: str | None,
) -> AbdmCareContext:
    # Serialize automatic completion, manual registration and reconciliation
    # for this patient. The unique constraint remains the final backstop.
    patient = (
        await db.execute(
            select(Patient)
            .where(
                Patient.id == patient_id,
                Patient.facility_id == facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if patient is None:
        raise DocumentUnavailable("No scoped patient for this document")
    reference = f"{kind}/{source_id}"
    source = await resolve_document(
        db,
        reference=reference,
        hi_type=SOURCE_TYPES[kind],
        patient_id=patient_id,
        facility_id=facility_id,
        visit_id=visit_id,
    )
    context = (
        await db.execute(
            select(AbdmCareContext).where(
                AbdmCareContext.patient_id == patient_id,
                AbdmCareContext.reference == reference,
            )
        )
    ).scalar_one_or_none()
    if context is None:
        context = AbdmCareContext(
            id=uuid.uuid4(),
            facility_id=facility_id,
            patient_id=patient_id,
            visit_id=visit_id,
            reference=reference,
            hi_type=SOURCE_TYPES[kind],
            display=display or f"{SOURCE_TYPES[kind]} — {source.authored_at.date().isoformat()}",
            document_at=source.authored_at,
            created_by=actor_id,
        )
        db.add(context)
        await db.flush()
    # Do not rewrite a legacy or changed document's identity/date here. Those
    # require explicit reconciliation and the resolver keeps them unshareable.
    await enqueue(db, kind="context_notify", target_id=context.id, facility_id=facility_id)
    return context


async def publish_document(
    db: AsyncSession,
    *,
    kind: str,
    source_id: uuid.UUID,
    visit: Visit,
    actor_id: uuid.UUID,
    display: str | None = None,
) -> AbdmCareContext:
    return await _publish(
        db,
        kind=kind,
        source_id=source_id,
        patient_id=visit.patient_id,
        facility_id=visit.facility_id,
        visit_id=visit.id,
        actor_id=actor_id,
        display=display,
    )


async def publish_source(
    db: AsyncSession,
    source: DocumentSource,
    *,
    patient_id: uuid.UUID,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID,
    display: str | None = None,
) -> AbdmCareContext:
    """Publish an already-resolved document, including one recorded outside a visit."""
    return await _publish(
        db,
        kind=source.kind,
        source_id=source.source_id,
        patient_id=patient_id,
        facility_id=facility_id,
        visit_id=source.visit.id if source.visit is not None else None,
        actor_id=actor_id,
        display=display,
    )


async def publish_immunization(
    db: AsyncSession, record: ImmunizationRecord, *, facility_id: uuid.UUID, actor_id: uuid.UUID
) -> AbdmCareContext:
    vaccine = await db.get(VaccineCatalogue, record.vaccine_id)
    given_at = record.administered_at
    if given_at.tzinfo is None:
        given_at = given_at.replace(tzinfo=UTC)
    given_on = given_at.astimezone(await facility_timezone(db, facility_id)).date()
    # ABDM cuts a display at 50 characters, so the label carries the short
    # catalogue code; "Bacillus Calmette-Guerin (BCG)" travels in the document.
    return await _publish(
        db,
        kind="immunization",
        source_id=record.id,
        patient_id=record.patient_id,
        facility_id=facility_id,
        visit_id=None,
        actor_id=actor_id,
        display=f"Immunization — {given_on.isoformat()} — {vaccine.code} dose {record.dose_number}",
    )


async def publish_invoice(db: AsyncSession, invoice: Invoice, actor_id: uuid.UUID) -> AbdmCareContext:
    """Offer an issued bill to the patient's ABHA as an InvoiceRecord, in the
    same transaction that issues it; nothing is sent until the patient links it."""
    visit = await db.get(Visit, invoice.visit_id)
    issued_at = invoice.issued_at
    if issued_at is None or visit is None:
        raise DocumentUnavailable("An invoice is shared only once issued")
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    issued_on = issued_at.astimezone(await facility_timezone(db, invoice.facility_id)).date()
    # The display carries no amounts or line items; ABDM cuts it at 50 characters.
    return await publish_document(
        db, kind="invoice", source_id=invoice.id, visit=visit, actor_id=actor_id,
        display=f"Invoice — {issued_on.isoformat()} — {invoice.invoice_number}"[:50],
    )


async def publish_released_document(
    db: AsyncSession, document: AbdmReleasedDocument, actor_id: uuid.UUID
) -> AbdmCareContext:
    """Offer a released PDF to the patient's ABHA as a HealthDocumentRecord, in
    the same transaction that releases it; nothing is sent until linked."""
    # ABDM cuts a display at 50 characters; the full title travels in the document.
    return await _publish(
        db,
        kind="document",
        source_id=document.id,
        patient_id=document.patient_id,
        facility_id=document.facility_id,
        visit_id=None,
        actor_id=actor_id,
        display=f"Document — {document.document_date.isoformat()} — {document.title}"[:50],
    )


async def publish_encounter(db: AsyncSession, encounter: Encounter, actor_id: uuid.UUID) -> None:
    visit = await db.get(Visit, encounter.visit_id)
    await publish_document(
        db, kind="encounter", source_id=encounter.id, visit=visit, actor_id=actor_id
    )
    prescriptions = (
        (
            await db.execute(
                select(Prescription).where(
                    Prescription.encounter_id == encounter.id,
                    Prescription.facility_id == visit.facility_id,
                    Prescription.patient_id == visit.patient_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for prescription in prescriptions:
        await publish_document(
            db, kind="prescription", source_id=prescription.id, visit=visit, actor_id=actor_id
        )
    has_vitals = (
        await db.execute(
            select(Vitals.id)
            .where(
                Vitals.encounter_id == encounter.id,
                Vitals.patient_id == visit.patient_id,
                Vitals.measured_at <= encounter.ended_at,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_vitals is not None:
        await publish_document(
            db, kind="wellness", source_id=encounter.id, visit=visit, actor_id=actor_id
        )


async def publish_order_document(
    db: AsyncSession, *, kind: str, source_id: uuid.UUID, order_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    order = await db.get(Order, order_id)
    encounter = await db.get(Encounter, order.encounter_id)
    visit = await db.get(Visit, encounter.visit_id)
    await publish_document(db, kind=kind, source_id=source_id, visit=visit, actor_id=actor_id)
