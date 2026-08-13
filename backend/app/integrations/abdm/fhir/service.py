"""FHIR R4 discharge-summary bundle stub (#216, B3-W5-01).

Not a real ABDM integration -- no gateway call, no HPR signing. Builds a
minimal, correctly-shaped Bundle dict for the discharge summary, then:

  1. enqueues it via app.outbox.service.enqueue() in the SAME transaction
     as the discharge write (schema.md §4A.3's dual-write rule)
  2. writes a FhirBundleTransaction row -- the Postgres audit fact this
     table exists for (§3 0026), stamped gateway_response_status =
     'stub_not_sent' since nothing has actually reached ABDM yet

Real HPR signing / gateway transmission is B7's territory per schema.md
§2 -- out of scope here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.abdm.fhir.models import FhirBundleTransaction
from app.admissions.models import Admission, Discharge
from app.outbox import service as outbox_service


def _build_discharge_summary_bundle(discharge: Discharge, admission: Admission) -> dict:
    return {
        "bundle_id": f"BDL-DISCHARGE-{uuid.uuid4()}",
        "record_type": "DischargeSummary",
        "resourceType": "Bundle",
        "type": "document",
        "entry": [{
            "resource": {
                "resourceType": "Composition",
                "admission_id": str(admission.id),
                "encounter_class": "IMP",
                "discharge_type": discharge.discharge_type,
                "discharge_summary": discharge.discharge_summary,
                "follow_up_date": (
                    discharge.follow_up_date.isoformat() if discharge.follow_up_date else None
                ),
                "destination_facility_id": (
                    str(discharge.destination_facility_id)
                    if discharge.destination_facility_id else None
                ),
                "destination_facility_name": discharge.destination_facility_name,
            },
        }],
    }


async def record_discharge_bundle(
    db: AsyncSession, discharge: Discharge, admission: Admission, facility_id
) -> FhirBundleTransaction:
    """#216 (B3-W5-01): discharge-summary FHIR stub -- durable outbox
    enqueue + FhirBundleTransaction audit row, gateway_response_status=
    'stub_not_sent'. No gateway call, no HPR signing (B7's territory,
    schema.md §2)."""
    bundle = _build_discharge_summary_bundle(discharge, admission)
    txn_id = uuid.uuid4()

    await outbox_service.enqueue(
        db,
        aggregate_type="fhir_bundle",
        aggregate_id=str(txn_id),
        event_type="discharge_summary_bundle_built",
        payload=bundle,
        sensitivity="important",
    )

    txn = FhirBundleTransaction(
        id=txn_id,
        bundle_id=bundle["bundle_id"],
        direction="hip_push",
        gateway_response_status="stub_not_sent",
        patient_id=admission.patient_id,
        transmitted_at=datetime.now(timezone.utc),
        facility_id=facility_id,
    )
    db.add(txn)
    await db.flush()
    return txn
