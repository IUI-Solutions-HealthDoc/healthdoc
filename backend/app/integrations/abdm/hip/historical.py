"""Explicit historical document registration; no facility-wide guessing or HTTP.

This is a privileged maintenance interface, not an authorization bypass for a
browser. The caller must own the transaction and roll it back on any refusal.
Operator attribution is separate from the source's clinical author.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditActor, actor_context
from app.integrations.abdm.hip.documents import (
    SOURCE_TYPES,
    DocumentUnavailable,
    resolve_context_document,
    resolve_document,
)
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.hip.publisher import publish_document
from app.nursing.models import Vitals
from app.patients.models import Patient
from app.users.models import Facility, User


class HistoricalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: uuid.UUID
    reference: str = Field(max_length=100)

    @model_validator(mode="after")
    def canonical_reference(self):
        try:
            kind, ident = self.reference.split("/", 1)
            canonical = f"{kind}/{uuid.UUID(ident)}"
        except ValueError as exc:
            raise ValueError("Canonical document reference required") from exc
        if kind not in SOURCE_TYPES or canonical != self.reference:
            raise ValueError("Canonical document reference required")
        return self


class HistoricalManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_id: uuid.UUID
    operator_id: uuid.UUID
    documents: list[HistoricalDocument] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_references(self):
        if len({d.reference for d in self.documents}) != len(self.documents):
            raise ValueError("Duplicate document reference")
        return self


class HistoricalResult(BaseModel):
    reference: str
    status: Literal["eligible", "existing", "refused", "created"]
    context_id: uuid.UUID | None = None
    document_at: datetime | None = None


class HistoricalRefused(ValueError):
    """Safe operator-facing code; never include patient data in the error."""


async def register_historical_documents(
    db: AsyncSession, manifest: HistoricalManifest, *, apply: bool = False
) -> list[HistoricalResult]:
    # These locks keep an operator/facility deactivation from racing the write.
    facility = (
        await db.execute(
            select(Facility)
            .where(Facility.id == manifest.facility_id, Facility.is_active)
            .with_for_update(read=True)
        )
    ).scalar_one_or_none()
    operator = (
        await db.execute(
            select(User)
            .where(
                User.id == manifest.operator_id,
                User.facility_id == manifest.facility_id,
                User.is_active,
            )
            .with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if facility is None or operator is None:
        raise HistoricalRefused("active_facility_operator_required")
    # Stable patient order prevents two overlapping manifests taking reverse
    # lock order. No scan of every patient or every clinical record is performed.
    patients = (
        (
            await db.execute(
                select(Patient)
                .where(
                    Patient.id.in_({d.patient_id for d in manifest.documents}),
                    Patient.facility_id == manifest.facility_id,
                    Patient.deleted_at.is_(None),
                    Patient.merged_into_patient_id.is_(None),
                )
                .order_by(Patient.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    patient_ids = {p.id for p in patients}
    results, sources = [], []
    for item in manifest.documents:
        try:
            if item.patient_id not in patient_ids:
                raise DocumentUnavailable("Unavailable")
            source = await resolve_document(
                db,
                reference=item.reference,
                hi_type=SOURCE_TYPES[item.reference.split("/")[0]],
                patient_id=item.patient_id,
                facility_id=manifest.facility_id,
                visit_id=None,
            )
            author = await db.get(User, source.author_id, populate_existing=True)
            # A former clinician may author a historical document; active status
            # is required for today's operator, not retroactively for its author.
            if (
                author is None
                or author.facility_id != manifest.facility_id
                or not author.registration_number
                or not author.registration_number.strip()
            ):
                raise DocumentUnavailable("Source author requires clinical review")
            if source.kind == "wellness":
                vitals = await db.scalar(
                    select(Vitals.id)
                    .where(
                        Vitals.encounter_id == source.source_id,
                        Vitals.patient_id == item.patient_id,
                        Vitals.measured_at <= source.authored_at,
                    )
                    .limit(1)
                )
                if vitals is None:
                    raise DocumentUnavailable("No measurements")
            existing = await db.scalar(
                select(AbdmCareContext).where(
                    AbdmCareContext.patient_id == item.patient_id,
                    AbdmCareContext.reference == item.reference,
                )
            )
            if existing is not None:
                if existing.facility_id != manifest.facility_id:
                    raise DocumentUnavailable("Unavailable")
                await resolve_context_document(db, existing)
            results.append(
                HistoricalResult(
                    reference=item.reference,
                    status="existing" if existing else "eligible",
                    context_id=existing.id if existing else None,
                    document_at=source.authored_at,
                )
            )
            sources.append(source)
        except DocumentUnavailable:
            # Do not distinguish absent, foreign, draft or unverifiable sources.
            results.append(HistoricalResult(reference=item.reference, status="refused"))
            sources.append(None)
    if not apply:
        return results
    if any(r.status == "refused" for r in results):
        raise HistoricalRefused("manifest_refused_preview_required")
    # A failure on a later document must not leave the first one applied, even
    # if an embedding caller catches the error and commits its outer transaction.
    # Use the ordinary ORM audit listener, not a duplicate manual CREATE log.
    # The operator UUID is attribution; the CLI cannot attest a Keycloak role.
    with actor_context(AuditActor(manifest.operator_id, None, None, None)):
        async with db.begin_nested():
            for result, source in zip(results, sources, strict=True):
                if result.status == "existing":
                    continue  # Never reset an existing notification job or adopted date.
                context = await publish_document(
                    db,
                    kind=source.kind,
                    source_id=source.source_id,
                    visit=source.visit,
                    actor_id=manifest.operator_id,
                )
                result.status, result.context_id = "created", context.id
                result.document_at = context.document_at
    return results
