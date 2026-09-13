"""Replay committed M2 responses without regenerating OTPs or mutable payloads."""

import json
from datetime import UTC, datetime

from app.common.security import decrypt_pii
from app.integrations.abdm.callback_replies import response_aad
from app.integrations.abdm.hip import gateway, link_otp
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.patients.models import Patient


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def dispatch(db, reply, job):
    from app.integrations.abdm.external_router import _contexts, _groups, _link_patient_contexts

    if (
        reply.response_encrypted is None
        or reply.response_expires_at is None
        or aware(reply.response_expires_at) <= datetime.now(UTC)
    ):
        raise ValueError("M2 response expired; explicit new patient action required")
    data = json.loads(
        decrypt_pii(
            reply.response_encrypted,
            associated_data=response_aad(reply.id, reply.facility_id, reply.kind),
        )
    )
    common = {"gateway_request_id": reply.gateway_request_id, "request_id": str(job.id)}
    if reply.kind == "hip_link_reject":
        await gateway.respond_to_link_confirm_error(
            **common, code="ABDM-1035", message="Incorrect OTP"
        )
        return
    if reply.kind == "hip_link_init":
        link = await db.get(AbdmCareContextLink, reply.target_id)
        if (
            link is None
            or link.facility_id != job.facility_id
            or link.status != "pending"
            or link.expires_at is None
            or aware(link.expires_at) <= datetime.now(UTC)
            or sorted(link.care_context_references) != reply.subject_ids
        ):
            raise ValueError("Pending M2 link is unavailable")
        patient, _ = await _link_patient_contexts(db, link)
        if patient.mobile != data["mobile"]:
            raise ValueError("M2 recipient changed; a new patient action is required")
        await link_otp.ensure_issued(
            link_ref_number=link.link_ref_number,
            mobile=patient.mobile,
            expires_at=aware(link.expires_at),
        )
        await gateway.respond_to_link_init(**common, **data["wire"])
        return
    patient = await db.get(Patient, reply.target_id) if reply.target_id else None
    if reply.target_id and (
        patient is None
        or patient.facility_id != job.facility_id
        or patient.deleted_at is not None
        or patient.merged_into_patient_id is not None
        or patient.abha_address != data["abha_address"]
    ):
        raise ValueError("M2 patient binding changed")
    if reply.kind == "hip_discover":
        if patient:
            contexts = await _contexts(
                db,
                facility_id=job.facility_id,
                patient_id=patient.id,
                references=set(reply.subject_ids),
            )
            if _groups(patient, contexts) != data["wire"]["patient_groups"]:
                raise ValueError("Discovery documents changed; cannot replay different facts")
        await gateway.respond_to_discovery_groups(**common, **data["wire"])
    elif reply.kind == "hip_profile":
        await gateway.acknowledge_profile_share(**common, **data["wire"])
    else:
        raise ValueError("Unsupported M2 response")
