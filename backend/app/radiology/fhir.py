"""
#204: Diagnostic Report FHIR bundle builder (DiagnosticReport + Observation).
"""
import uuid
from datetime import datetime, timezone

from app.radiology.models import RadiologyOrderItem, RadiologyReport


_STATUS_MAP = {
    "preliminary": "preliminary",
    "final": "final",
    "corrected": "corrected",
}


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC with Z suffix, per Master Schema §4.2."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_diagnostic_report_bundle(
    *,
    order_item: RadiologyOrderItem,
    report: RadiologyReport,
    patient_id: uuid.UUID,
) -> dict:
    diagnostic_report_id = str(uuid.uuid4())
    observation_id = str(uuid.uuid4())
    now_iso = _iso_z(datetime.now(timezone.utc))

    fhir_status = _STATUS_MAP.get(report.status, "unknown")

    observation = {
        "resourceType": "Observation",
        "id": observation_id,
        "status": fhir_status,
        "code": {"text": order_item.scan_type},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": (
            _iso_z(order_item.scheduled_at) if order_item.scheduled_at else now_iso
        ),
        "valueString": report.findings,
    }

    diagnostic_report = {
        "resourceType": "DiagnosticReport",
        "id": diagnostic_report_id,
        "status": fhir_status,
        "code": {"text": order_item.modality},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": (
            _iso_z(order_item.scheduled_at) if order_item.scheduled_at else now_iso
        ),
        "issued": _iso_z(report.created_at),
        "performer": [{"reference": f"Practitioner/{report.created_by}"}],
        "result": [{"reference": f"Observation/{observation_id}"}],
        "conclusion": report.impression,
        "identifier": [
            {
                "system": "urn:healthdoc:accession-number",
                "value": order_item.accession_number,
            }
        ],
    }

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": now_iso,
        "entry": [
            {"resource": diagnostic_report},
            {"resource": observation},
        ],
    }
    return bundle
