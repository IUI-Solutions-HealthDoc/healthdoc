"""Listing forms and order sets must not write.

Both GET routes used to insert the default catalogue on first read, inside a
bare `except` that rolled back and hid any failure. Seeding now belongs to the
seed script alone.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.auth.deps import DbUser
from app.forms import router as forms_router
from app.forms.models import ClinicalOrderSet, FormDefinition
from app.forms.service import DEFAULT_FORMS, DEFAULT_ORDER_SETS, ensure_defaults_seeded
from app.users.models import Facility, User

pytestmark = pytest.mark.asyncio


async def _admin(db) -> DbUser:
    facility = Facility(id=uuid.uuid4(), code=f"F{uuid.uuid4().hex[:6]}", name="F", state_code="DL")
    user = User(
        id=uuid.uuid4(),
        keycloak_sub=f"forms-{uuid.uuid4()}",
        username=f"forms-{uuid.uuid4().hex[:8]}",
        full_name="Forms Admin",
        facility_id=facility.id,
    )
    db.add_all([facility, user])
    await db.flush()
    return DbUser(
        id=user.id, keycloak_sub=user.keycloak_sub, username=user.username,
        facility_id=facility.id, roles=["admin"],
    )


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_listing_an_empty_catalogue_writes_nothing(db):
    forms = await forms_router.list_form_definitions(db=db, status_filter="published")
    order_sets = await forms_router.list_order_sets(db=db, category=None)

    assert forms == []
    assert order_sets == []
    assert await _count(db, FormDefinition) == 0
    assert await _count(db, ClinicalOrderSet) == 0


async def test_seed_fills_only_missing_codes_and_is_repeatable(db):
    caller = await _admin(db)
    db.add(FormDefinition(
        id=uuid.uuid4(), code=DEFAULT_FORMS[0]["code"], title="Locally edited", version=2,
        status="published", fields_schema=DEFAULT_FORMS[0]["fields_schema"], created_by=caller.id,
    ))
    await db.flush()

    await ensure_defaults_seeded(db, caller.id)
    await ensure_defaults_seeded(db, caller.id)

    assert await _count(db, FormDefinition) == len(DEFAULT_FORMS)
    assert await _count(db, ClinicalOrderSet) == len(DEFAULT_ORDER_SETS)
    kept = await db.scalar(select(FormDefinition.title).where(FormDefinition.code == DEFAULT_FORMS[0]["code"]))
    assert kept == "Locally edited"
