"""Read-only operational metadata. Never prints patient data, tokens or secrets."""

import argparse
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text

from app.common.db import SessionLocal
from app.consent.models import ConsentRecord
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.integrations.abdm.hiu.models import AbdmHiuHealthInformationRequest, AbdmReceivedBundle
from app.integrations.abdm.jobs import AbdmJob
from app.users.models import User


async def status(link_id=None, consent_id=None):
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
        if link_id:
            row = (
                (
                    await db.execute(
                        select(
                            AbdmCareContextLink.status,
                            AbdmCareContextLink.token_request_id,
                            AbdmCareContextLink.link_token_encrypted.is_not(None).label(
                                "token_present"
                            ),
                            AbdmCareContextLink.confirmed_at,
                        ).where(AbdmCareContextLink.id == link_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            output["selected_link"] = dict(row) if row else None
        if consent_id:
            row = (
                await db.execute(
                    select(ConsentRecord.status, ConsentRecord.expires_at).where(
                        ConsentRecord.id == consent_id
                    )
                )
            ).one_or_none()
            output["local_consent_valid"] = bool(
                row and row.status == "granted" and row.expires_at and row.expires_at > now
            )
        staff = (
            (
                await db.execute(
                    select(
                        User.registration_number.is_not(None).label("number_configured"),
                        User.registration_identifier_type.is_not(None).label("type_configured"),
                        User.registration_identifier_system.is_not(None).label(
                            "registry_configured"
                        ),
                    ).where(User.username == "dev.doctor")
                )
            )
            .mappings()
            .one_or_none()
        )
        output["dev_requester"] = dict(staff) if staff else None
        print(json.dumps(output, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--link-id", type=uuid.UUID)
    parser.add_argument("--consent-id", type=uuid.UUID)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    asyncio.run(status(args.link_id, args.consent_id))
