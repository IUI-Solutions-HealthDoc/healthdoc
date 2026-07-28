import uuid
from sqlalchemy.orm import Session
from app.fhir.models import FhirBundleTransaction


def stub_fhir_bundle_transaction(db: Session, discharge, admission):
    tx = FhirBundleTransaction(
        bundle_id=f"discharge-{discharge.id}",
        abdm_request_id=None,
        direction="hip_push",
        care_context_linked=False,
        gateway_response_status="stubbed",  # not actually sent yet
        signed_by_hpr_id=None,
        patient_id=admission.patient_id,
        consent_id=None,
        transmitted_at=discharge.discharged_at,
    )
    db.add(tx)
    db.commit()
    return tx