"""Two real connections: duplicate retry waits; rollback leaves no partial record."""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import DbUser
from app.common.clinical_write import clinical_write
from app.common.idempotency_models import IdempotencyKey
from app.forms.models import FormDefinition, FormSubmission
from app.forms.schemas import FormSubmissionCreate, FormSubmissionOut
from app.forms.service import create_submission
from app.patients.models import Patient
from app.users.models import Facility, User


@pytest.mark.asyncio
@pytest.mark.parametrize("first_rolls_back", [False, True])
async def test_concurrent_clinical_retry_commits_one_record_and_receipt(first_rolls_back):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit TEST_DATABASE_URL; no application database fallback")
    engine = create_async_engine(url)
    assert "test" in (engine.url.database or "").lower(), "Dedicated test database required"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:12]
    facility_id, actor_id, patient_id, form_id = [uuid.uuid4() for _ in range(4)]
    key = str(uuid.uuid4())
    first_written, release_first, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        async with Session.begin() as db:
            for row in [
                Facility(id=facility_id, code="CW" + suffix, name="Synthetic retry test", state_code="TS"),
                User(id=actor_id, facility_id=facility_id, keycloak_sub="retry-" + suffix,
                     username="retry-" + suffix, full_name="Synthetic clinician"),
                Patient(id=patient_id, facility_id=facility_id, uhid="RETRY-" + suffix,
                        full_name="Synthetic patient", sex="unknown", age_years=30,
                        identity_path="demographics_only", created_by=actor_id),
                FormDefinition(id=form_id, code="RETRY-" + suffix, title="Synthetic form", version=1,
                               status="published", created_by=actor_id, fields_schema=[
                                   {"id": "answer", "label": "Answer", "type": "text"}]),
            ]:
                db.add(row)
                await db.flush()
        actor = DbUser(id=actor_id, facility_id=facility_id, keycloak_sub="retry-" + suffix,
                       username="retry-" + suffix, roles=["doctor"])
        payload = FormSubmissionCreate(patient_id=patient_id, form_id=form_id, form_data={"answer": "Test"})

        async def request(first=False):
            async with Session() as db:
                if not first:
                    second_started.set()
                async def write():
                    result = await create_submission(db, payload, actor.id)
                    if first:
                        first_written.set()
                        await asyncio.wait_for(release_first.wait(), 10)
                        if first_rolls_back:
                            raise RuntimeError("Synthetic interrupted transaction")
                    return result
                return await clinical_write(db, key, "POST /forms/submissions", payload,
                                            actor, FormSubmissionOut, write)

        first = asyncio.create_task(request(first=True))
        tasks.append(first)
        await asyncio.wait_for(first_written.wait(), 10)
        second = asyncio.create_task(request())
        tasks.append(second)
        await asyncio.wait_for(second_started.wait(), 10)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), 0.25)
        release_first.set()
        if first_rolls_back:
            with pytest.raises(RuntimeError, match="Synthetic interrupted"):
                await asyncio.wait_for(first, 10)
        else:
            original = await asyncio.wait_for(first, 10)
        replay = await asyncio.wait_for(second, 10)
        if not first_rolls_back:
            assert replay.model_dump() == original.model_dump()
        async with Session() as db:
            assert await db.scalar(select(func.count()).select_from(FormSubmission).where(
                FormSubmission.form_id == form_id)) == 1
            receipt = (await db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))).scalar_one()
            assert receipt.response_status == 201
            assert receipt.response_body["id"] == str(replay.id)
    finally:
        release_first.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()
