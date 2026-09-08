"""Clinical completion → scoped document registry, atomically and without HTTP."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.abdm.hip.documents import SOURCE_TYPES, DocumentUnavailable, resolve_document
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.jobs import enqueue
from app.nursing.models import Vitals
from app.opd.models import Encounter, Visit
from app.orders.models import Order, Prescription
from app.patients.models import Patient


async def publish_document(
    db: AsyncSession,
    *,
    kind: str,
    source_id: uuid.UUID,
    visit: Visit,
    actor_id: uuid.UUID,
    display: str | None = None,
) -> AbdmCareContext:
    # Serialize automatic completion, manual registration and reconciliation
    # for this patient. The unique constraint remains the final backstop.
    patient = (
        await db.execute(
            select(Patient)
            .where(
                Patient.id == visit.patient_id,
                Patient.facility_id == visit.facility_id,
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
        patient_id=visit.patient_id,
        facility_id=visit.facility_id,
        visit_id=visit.id,
    )
    context = (
        await db.execute(
            select(AbdmCareContext).where(
                AbdmCareContext.patient_id == visit.patient_id,
                AbdmCareContext.reference == reference,
            )
        )
    ).scalar_one_or_none()
    if context is None:
        context = AbdmCareContext(
            id=uuid.uuid4(),
            facility_id=visit.facility_id,
            patient_id=visit.patient_id,
            visit_id=visit.id,
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
    await enqueue(db, kind="context_notify", target_id=context.id, facility_id=visit.facility_id)
    return context


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
