"""Freeze an exact pre-cutover ABDM queue; never dispatch or delete jobs.

Dry-run by default. Run only after migration 0088, with the delivery worker
stopped, an application-database backup, and an explicitly reviewed cutoff.
"""

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.common.db import SessionLocal
from app.integrations.abdm.jobs import AbdmJob, freeze_pending_before
from app.users.models import Facility


def utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Cutoff must include a UTC offset")
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise argparse.ArgumentTypeError("Cutoff cannot be in the future")
    return parsed


async def freeze(
    *, facility_id: uuid.UUID, hfr_id: str, before: datetime, expected_count: int, apply: bool
) -> int:
    async with SessionLocal() as db:
        facility = await db.get(Facility, facility_id)
        if facility is None or facility.hfr_facility_id != hfr_id:
            raise ValueError("Facility and HFR ID do not match; no jobs frozen")
        leased = (
            await db.execute(
                select(func.count())
                .select_from(AbdmJob)
                .where(AbdmJob.facility_id == facility_id, AbdmJob.status == "leased")
            )
        ).scalar_one()
        if leased:
            raise ValueError("Leased jobs exist; stop the worker and inspect them first")
        count = await freeze_pending_before(
            db,
            facility_id=facility_id,
            before=before,
            expected_count=expected_count,
        )
        if apply:
            await db.commit()
        else:
            await db.rollback()
        return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facility-id", type=uuid.UUID, required=True)
    parser.add_argument("--expected-hfr-id", required=True)
    parser.add_argument("--before", type=utc_timestamp, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    count = asyncio.run(
        freeze(
            facility_id=args.facility_id,
            hfr_id=args.expected_hfr_id,
            before=args.before,
            expected_count=args.expected_count,
            apply=args.apply,
        )
    )
    print(
        json.dumps(
            {
                "facility_id": str(args.facility_id),
                "expected_hfr_id": args.expected_hfr_id,
                "before": args.before.isoformat().replace("+00:00", "Z"),
                "count": count,
                "state": "frozen" if args.apply else "dry_run_rolled_back",
            }
        )
    )
