"""Preview one lost sandbox callback; --apply requeues it but sends nothing.

Run inside the configured backend: python -m scripts.retry_abdm_token_callback
--link-id UUID [--apply]. Inspect the callback failure and obtain participant
transmission permission first. Never start the general worker for this action.
"""

import argparse
import asyncio
import json
import uuid

from app import main as app_main  # noqa: F401 -- metadata and audit listeners
from app.common.config import get_settings
from app.common.db import SessionLocal
from app.integrations.abdm.hip.documents import DocumentUnavailable
from app.integrations.abdm.hip.models import AbdmCareContextLink
from app.integrations.abdm.hip.recovery import queue_token_callback_retry


async def run(link_id: uuid.UUID, apply: bool) -> None:
    settings = get_settings()
    if (
        settings.environment != "dev"
        or settings.abdm_gateway_base_url != "https://dev.abdm.gov.in"
        or settings.abdm_x_cm_id != "sbx"
    ):
        raise DocumentUnavailable("This maintenance command is sandbox-only")
    async with SessionLocal() as db:
        link = await db.get(AbdmCareContextLink, link_id)
        if link is None:
            raise DocumentUnavailable("Link unavailable")
        ident = await queue_token_callback_retry(
            db, link_id=link.id, facility_id=link.facility_id, apply=apply
        )
        if apply:
            await db.commit()
        else:
            await db.rollback()
    print(json.dumps({"job_id": str(ident), "queued": apply, "outbound_sent": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--link-id", required=True, type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.link_id, args.apply))
    except DocumentUnavailable as exc:
        parser.exit(1, f"Recovery refused: {exc}\n")
