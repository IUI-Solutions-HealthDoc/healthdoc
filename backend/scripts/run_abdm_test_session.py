"""Sandbox delivery for new work in one facility. Dry-run unless --execute.

The cutoff defaults to process start. On restart, explicitly reuse the printed
cutoff to recover this session's work. Frozen jobs, earlier jobs and other
facilities are excluded inside the atomic claim. Existing retry/lease limits
remain in force. This is not the global delivery/retention worker.
"""

import argparse
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.common.config import get_settings
from app.common.db import SessionLocal
from app.integrations.abdm.job_runner import run_once
from app.integrations.abdm.jobs import AbdmJob
from app.users.models import Facility
from scripts.freeze_abdm_jobs import utc_timestamp


async def check_scope(facility_id, service_id):
    settings = get_settings()
    if (
        settings.abdm_gateway_base_url.rstrip("/") != "https://dev.abdm.gov.in"
        or settings.abdm_x_cm_id != "sbx"
        or any(
            value != service_id
            for value in (settings.abdm_hfr_facility_id, settings.abdm_hip_id, settings.abdm_hiu_id)
        )
    ):
        raise ValueError("Sandbox gateway/CM and HFR/HIP/HIU must match the expected service")
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        facility = await db.get(Facility, facility_id)
        if facility is None or facility.hfr_facility_id != service_id:
            raise ValueError("Local facility does not match the expected service")


async def run_session(*, facility_id, service_id, since, execute):
    if since.tzinfo is None or since.utcoffset() is None or since > datetime.now(UTC):
        raise ValueError("Session cutoff must be timezone-aware and not in the future")
    await check_scope(facility_id, service_id)
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        rows = (
            await db.execute(
                select(AbdmJob.id, AbdmJob.kind, AbdmJob.status)
                .where(
                    AbdmJob.facility_id == facility_id,
                    AbdmJob.created_at >= since,
                    AbdmJob.status.in_(["pending", "leased"]),
                )
                .order_by(AbdmJob.created_at)
                .limit(100)
            )
        ).all()
    print(
        json.dumps(
            {
                "mode": "delivery_session" if execute else "dry_run_no_dispatch",
                "facility_id": str(facility_id),
                "service_id": service_id,
                "created_since": since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "jobs_in_scope_first_100": [dict(row._mapping) for row in rows],
                "historical_frozen_jobs_included": False,
            },
            default=str,
        ),
        flush=True,
    )
    if not execute:
        return
    while True:
        await check_scope(facility_id, service_id)
        claimed = await run_once(facility_id=facility_id, created_since=since)
        if claimed:
            print(
                json.dumps(
                    {
                        "attempt_completed_at": datetime.now(UTC).isoformat(),
                        "note": "Inspect delivery status and callbacks; an attempt is not business success.",
                    }
                ),
                flush=True,
            )
        else:
            await asyncio.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facility-id", required=True, type=uuid.UUID)
    parser.add_argument("--expected-service-id", required=True)
    parser.add_argument("--created-since", type=utc_timestamp)
    parser.add_argument("--execute", action="store_true")
    options = parser.parse_args()
    # Load the same SQLAlchemy model registry/listeners as the running API.
    from app import main as app_main  # noqa: F401

    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(
            run_session(
                facility_id=options.facility_id,
                service_id=options.expected_service_id,
                since=options.created_since or datetime.now(UTC),
                execute=options.execute,
            )
        )
    except KeyboardInterrupt:
        print("Session delivery stopped. HealthDoc and its webhook remain running.")
    except Exception as exc:
        # Database/HTTP errors can contain parameters: never print exception bodies.
        print(
            f"Session stopped ({type(exc).__name__}); inspect configuration and redacted delivery status.",
            flush=True,
        )
        raise SystemExit(1) from None
