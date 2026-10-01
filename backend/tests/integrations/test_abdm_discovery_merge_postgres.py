"""A patient merge moves a discovery match with the links it starts (real Postgres).

The merge repointer is raw SQL, which the SQLite fixture cannot bind UUIDs for,
so this runs against the dedicated test database like the other *_postgres tests.
"""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.abdm.hip import discovery
from app.integrations.abdm.hip.models import AbdmCareContextLink, AbdmDiscoveryMatch
from app.patients import service as patient_service
from app.patients.models import Patient
from app.users.models import Facility, User


@pytest.mark.asyncio
async def test_merge_repoints_the_match_and_its_link_together():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit TEST_DATABASE_URL; no application database fallback")
    engine = create_async_engine(url)
    assert "test" in (engine.url.database or "").lower(), "Dedicated test database required"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    facility_id, actor_id, source_id, target_id = (uuid.uuid4() for _ in range(4))
    transaction_id = f"txn-{suffix}"
    try:
        async with Session.begin() as db:
            for row in [
                Facility(id=facility_id, code="DM" + suffix, name="Synthetic merge", state_code="TS"),
                User(id=actor_id, facility_id=facility_id, keycloak_sub="dm-" + suffix,
                     username="dm-" + suffix, full_name="Synthetic desk"),
                Patient(id=source_id, facility_id=facility_id, uhid="DM-S-" + suffix,
                        full_name="Synthetic Source", sex="male", age_years=36,
                        mobile="+919876543210", identity_path="demographics_only",
                        created_by=actor_id),
                Patient(id=target_id, facility_id=facility_id, uhid="DM-T-" + suffix,
                        full_name="Synthetic Source", sex="male", age_years=36,
                        identity_path="demographics_only", created_by=actor_id),
            ]:
                db.add(row)
                await db.flush()
            db.add(AbdmDiscoveryMatch(
                id=discovery.match_id(facility_id, transaction_id), facility_id=facility_id,
                patient_id=source_id, transaction_id=transaction_id, abha_address="dm@sbx",
                care_context_references=[], matched_by=["MOBILE"],
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            ))
            db.add(AbdmCareContextLink(
                id=uuid.uuid4(), facility_id=facility_id, patient_id=source_id,
                abha_address="dm@sbx", transaction_id=transaction_id,
                care_context_references=[], status="pending",
            ))
        async with Session.begin() as db:
            source, target = await db.get(Patient, source_id), await db.get(Patient, target_id)
            await patient_service._repoint_abdm_records(db, source=source, target=target)
        async with Session() as db:
            match = await db.get(AbdmDiscoveryMatch, discovery.match_id(facility_id, transaction_id))
            link = (await db.execute(
                AbdmCareContextLink.__table__.select().where(
                    AbdmCareContextLink.transaction_id == transaction_id))).first()
            assert match.patient_id == target_id == link.patient_id
            assert await discovery.link_began_from_match(db, link)
    finally:
        # Synthetic, uniquely named rows stay, like the other *_postgres tests:
        # append-only audit rows reference the facility.
        await engine.dispose()
