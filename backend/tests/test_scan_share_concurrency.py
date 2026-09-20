"""Real PostgreSQL locking proof. Runs in CI; never uses the application DB fallback."""
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import DbUser
from app.integrations.abdm.models import ScanShareTicket
from app.integrations.abdm.scan_share_router import ScanShareCheckInPayload, check_in_scan_share_ticket
from app.users.models import Facility


@pytest.mark.asyncio
async def test_two_desks_cannot_reassign_the_same_reception_ticket():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit TEST_DATABASE_URL; never falls back to patient database")
    engine = create_async_engine(url)
    assert "test" in (engine.url.database or "").lower(), "Use a dedicated test database"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    facility_id, ticket_id = uuid.uuid4(), uuid.uuid4()
    caller = DbUser(id=uuid.uuid4(), keycloak_sub="synthetic-checkin", username="test-reception",
                    facility_id=facility_id, roles=["receptionist"])
    try:
        async with Session.begin() as db:
            db.add(Facility(id=facility_id, code="SS" + uuid.uuid4().hex[:8],
                            name="Synthetic reception concurrency", state_code="TS"))
        async with Session.begin() as db:
            db.add(ScanShareTicket(id=ticket_id, facility_id=facility_id, token_number="123",
                                  abha_address="synthetic@sbx", profile_data={}, status="active",
                                  expires_at=datetime.now(UTC) + timedelta(minutes=30)))

        async def check_in(counter):
            try:
                async with Session.begin() as db:
                    result = await check_in_scan_share_ticket(
                        str(ticket_id), ScanShareCheckInPayload(counter=counter), caller, db,
                    )
                    return result
            except HTTPException as exc:
                assert exc.status_code == 409
                assert exc.detail["code"] == "ticket_already_checked_in"
                return None

        attempts = await asyncio.wait_for(asyncio.gather(check_in("Desk A"), check_in("Desk B")), timeout=10)
        winners = [result for result in attempts if result is not None]
        assert len(winners) == 1
        winner = winners[0]
        async with Session() as db:
            stored = await db.scalar(select(ScanShareTicket).where(ScanShareTicket.id == ticket_id))
            assert stored.counter == winner.counter
            assert stored.checked_in_at == winner.check_in_time
        replay = await check_in(winner.counter)
        assert replay.model_dump() == winner.model_dump()
    finally:
        async with Session.begin() as db:
            await db.execute(delete(ScanShareTicket).where(ScanShareTicket.id == ticket_id))
        # Preserve any facility audit history rather than deleting around audit FKs.
        await engine.dispose()
