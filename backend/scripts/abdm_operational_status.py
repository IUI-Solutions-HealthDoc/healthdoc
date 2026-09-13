"""Read-only operational metadata. Never prints patient data, tokens or secrets."""

import argparse
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text

from app.common.db import SessionLocal
from app.consent.models import ConsentPurpose, ConsentRecord
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.integrations.abdm.hiu.models import AbdmHiuHealthInformationRequest, AbdmReceivedBundle
from app.integrations.abdm.hiu.requester import RequesterUnavailable, from_staff
from app.integrations.abdm.jobs import AbdmJob, job_id
from app.users.models import User


def link_stage(link, token_job, *, now):
    """Metadata diagnosis, never a retry recommendation or permission to share."""
    if link is None:
        return "not_selected_or_missing"
    if link.status == "confirmed":
        return "confirmed" if link.confirmed_at else "inconsistent_confirmation"
    if link.status in {"expired", "failed"}:
        return "stopped"
    if link.token_present:
        if link.token_use_until is None or link.token_use_until <= now:
            return "token_use_window_expired"
        return "token_received_link_confirmation_pending"
    if token_job is None:
        return "token_job_missing"
    return {
        "pending": "token_dispatch_pending",
        "leased": "token_dispatch_in_progress_or_lease_expired",
        "done": "token_callback_missing_dispatch_completion_is_not_acceptance",
        "dead": "token_dispatch_stopped_inspect_before_retry",
    }.get(token_job.status, "unknown_job_state")


def consent_metadata(consent, link, *, now):
    """Local lifecycle only. Scope, visit, role and PHR permission remain separate."""
    return {
        "present": consent is not None,
        "matches_selected_patient": bool(
            consent and link and consent.patient_id == link.patient_id
        ),
        "clinical_review_purpose": bool(consent and consent.purpose_code == "clinical_review"),
        "active_at_check": bool(
            consent
            and consent.status == "granted"
            and consent.granted_at <= now
            and (consent.expires_at is None or consent.expires_at > now)
        ),
        "authorizes_transmission": False,
        "scope_and_phr_approval_checked": False,
    }


def requester_metadata(staff, link):
    if link is None:
        return {
            "profile_complete_for_selected_facility": False,
            "registry_membership_verified": False,
        }
    try:
        from_staff(staff, link.facility_id)
        complete = True
    except RequesterUnavailable:
        complete = False
    return {
        "profile_complete_for_selected_facility": complete,
        "registry_membership_verified": False,
    }


async def status(link_id=None, consent_id=None, requester_username="dev.doctor"):
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        output = {"checked_at": now.isoformat()}
        grouped = (
            await db.execute(
                select(AbdmJob.kind, AbdmJob.status, func.count()).group_by(
                    AbdmJob.kind, AbdmJob.status
                )
            )
        ).all()
        output["jobs"] = [{"kind": k, "status": s, "count": n} for k, s, n in grouped]
        for label, model, column in [
            ("received_content_rows", AbdmReceivedBundle, AbdmReceivedBundle.content_encrypted),
            (
                "stored_transfer_keys",
                AbdmHiuHealthInformationRequest,
                AbdmHiuHealthInformationRequest.private_key_encrypted,
            ),
            ("stored_link_tokens", AbdmCareContextLink, AbdmCareContextLink.link_token_encrypted),
        ]:
            output[label] = await db.scalar(
                select(func.count()).select_from(model).where(column.is_not(None))
            )
        link = None
        if link_id:
            link = (
                await db.execute(
                    select(
                        AbdmCareContextLink.status,
                        AbdmCareContextLink.facility_id,
                        AbdmCareContextLink.patient_id,
                        AbdmCareContextLink.token_request_id,
                        AbdmCareContextLink.link_token_encrypted.is_not(None).label(
                            "token_present"
                        ),
                        AbdmCareContextLink.token_use_until,
                        AbdmCareContextLink.confirmed_at,
                    ).where(AbdmCareContextLink.id == link_id)
                )
            ).one_or_none()
            token_job = (
                (
                    await db.execute(
                        select(AbdmJob.status, AbdmJob.attempts).where(
                            AbdmJob.id == job_id("link_token", link_id),
                            AbdmJob.target_id == link_id,
                            AbdmJob.kind == "link_token",
                            AbdmJob.facility_id == link.facility_id,
                        )
                    )
                ).one_or_none()
                if link
                else None
            )
            output["selected_link"] = (
                {
                    "status": link.status,
                    "token_request_id": link.token_request_id,
                    "token_present": link.token_present,
                    "confirmed_at": link.confirmed_at,
                    "stage": link_stage(link, token_job, now=now),
                    "token_job": dict(token_job._mapping) if token_job else None,
                }
                if link
                else None
            )
        if consent_id:
            row = (
                await db.execute(
                    select(
                        ConsentRecord.status,
                        ConsentRecord.patient_id,
                        ConsentRecord.granted_at,
                        ConsentRecord.expires_at,
                        ConsentPurpose.purpose_code,
                    )
                    .join(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
                    .where(ConsentRecord.id == consent_id)
                )
            ).one_or_none()
            output["local_consent"] = consent_metadata(row, link, now=now)
        staff = (
            await db.execute(
                select(
                    User.full_name,
                    User.is_active,
                    User.facility_id,
                    User.registration_number,
                    User.registration_identifier_type,
                    User.registration_identifier_system,
                ).where(User.username == requester_username)
            )
        ).one_or_none()
        output["requester"] = requester_metadata(staff, link)
        output["live_exchange_verified"] = False
        print(json.dumps(output, default=str))
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--link-id", type=uuid.UUID)
    parser.add_argument("--consent-id", type=uuid.UUID)
    parser.add_argument("--requester-username", default="dev.doctor")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(status(args.link_id, args.consent_id, args.requester_username))
