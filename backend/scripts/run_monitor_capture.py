"""Capture every active facility's pulse for the control room.

Usage:
    python -m scripts.run_monitor_capture --once
    python -m scripts.run_monitor_capture            # every 15 minutes until stopped

Each round commits on its own, so a crash loses at most one round. Captures
older than the retention window are deleted at the end of a round: the board
reads the last day, and trends beyond 90 days belong in a daily rollup.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.common.db import SessionLocal
from app.monitor.models import FacilityPulse
from app.monitor.service import CAPTURE_INTERVAL, capture_all

RETENTION = timedelta(days=90)
log = logging.getLogger("monitor.capture")


async def one_round() -> int:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        captured = await capture_all(db, now=now)
        await db.execute(delete(FacilityPulse).where(FacilityPulse.captured_at < now - RETENTION))
        await db.commit()
    log.info("captured %d facilities at %s", captured, now.isoformat())
    return captured


async def main(once: bool) -> None:
    while True:
        started = datetime.now(UTC)
        try:
            await one_round()
        except Exception:
            # Keep the loop alive; the board shows facilities as not reporting
            # once captures stop, which is the signal an operator needs.
            log.exception("capture round failed")
            if once:
                raise
        if once:
            return
        elapsed = datetime.now(UTC) - started
        await asyncio.sleep(max(0.0, (CAPTURE_INTERVAL - elapsed).total_seconds()))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="capture one round and exit")
    asyncio.run(main(parser.parse_args().once))
