"""Stub FHIR R4 bundle builders wired to OPD visit close (#201, B3-W4-02).

Not a real ABDM integration -- no gateway call, no HPR signing. Builds a
minimal, correctly-shaped Bundle dict for the OPD note (from the
encounter's SOAP fields, 0021) and for each prescription on the visit's
encounters, then:

  1. enqueues it via app.outbox.service.enqueue() in the SAME transaction
     as the visit-close write (schema.md §4A.3's dual-write rule -- the
     payload rides the same outbox any clinical note projection already
     uses, rather than a second bespoke write path)
  2. writes a FhirBundleTransaction row -- the Postgres audit fact this
     table exists for (§3 0026), stamped gateway_response_status =
     'stub_not_sent' since nothing has actually reached ABDM yet

Real HPR signing / gateway transmission is B7's territory per schema.md
§2 -- out of scope here; this only wires the encounter-close trigger and
produces a correctly-shaped, durably-recorded stub.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.abdm.fhir.models import FhirBundleTransaction
from app.opd.models import Encounter, Visit
from app.orders.models import Prescription, PrescriptionItem
from app.outbox import service as outbox_service


def _build_opd_note_bundle(encounter: Encounter) -> dict:
    return {
        "bundle_id": f"BDL-NOTE-{uuid.uuid4()}",
        "record_type": "OPConsultRecord",
        "resourceType": "Bundle",
        "type": "document",
        "entry": [{
            "resource": {
                "resourceType": "Composition",
                "encounter_id": str(encounter.id),
                "section": [
                    {"title": "Subjective", "text": encounter.subjective},
                    {"title": "Objective", "text": encounter.objective},
                    {"title": "Assessment", "text": encounter.assessment},
                    {"title": "Plan", "text": encounter.plan},
                ],
            },
        }],
    }


def _build_prescription_bundle(prescription: Prescription, items: list[PrescriptionItem]) -> dict:
    return {
        "bundle_id": f"BDL-RX-{uuid.uuid4()}",
        "record_type": "Prescription",
        "resourceType": "Bundle",
        "type": "document",
        "entry": [
            {"resource": {
                "resourceType": "MedicationRequest",
                "prescription_id": str(prescription.id),
                "medication_name": item.medicine_name,
                "dosage": item.dosage,
                "frequency": item.frequency,
                # duration_days omitted: its column is typed UUID in the
                # current model (pre-existing bug from #181, out of scope
                # here -- not touched so as not to widen this PR).
            }}
            for item in items
        ],
    }


async def _record_bundle(db: AsyncSession, visit: Visit, bundle: dict) -> FhirBundleTransaction:
    txn_id = uuid.uuid4()

    await outbox_service.enqueue(
        db,
        aggregate_type="fhir_bundle",
        aggregate_id=str(txn_id),
        event_type=f"{bundle['record_type'].lower()}_bundle_built",
        payload=bundle,
        sensitivity="important",
    )

    txn = FhirBundleTransaction(
        id=txn_id,
        bundle_id=bundle["bundle_id"],
        direction="hip_push",
        gateway_response_status="stub_not_sent",
        patient_id=visit.patient_id,
        transmitted_at=datetime.now(timezone.utc),
        facility_id=visit.facility_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def build_encounter_close_bundles(db: AsyncSession, visit: Visit) -> list[FhirBundleTransaction]:
    """Called from opd.service.transition_visit_status() once a visit
    reaches 'closed'. Best-effort: an encounter with no stored note, or a
    prescription with no items, simply produces fewer bundles -- this
    never blocks or fails the visit-close transition itself."""
    created: list[FhirBundleTransaction] = []

    encounters = (await db.execute(
        select(Encounter).where(Encounter.visit_id == visit.id)
    )).scalars().all()

    for encounter in encounters:
        if encounter.note_status == "stored":
            created.append(await _record_bundle(db, visit, _build_opd_note_bundle(encounter)))

        prescriptions = (await db.execute(
            select(Prescription).where(Prescription.encounter_id == encounter.id)
        )).scalars().all()

        for prescription in prescriptions:
            items = (await db.execute(
                select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)
            )).scalars().all()
            if not items:
                continue
            created.append(await _record_bundle(db, visit, _build_prescription_bundle(prescription, items)))

    return created
