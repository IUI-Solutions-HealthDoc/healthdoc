"""Suppliers can be added (QA 10 Oct 2026): the purchase-order supplier list was
empty on every facility and nothing could add one."""
import uuid
from types import SimpleNamespace

import pytest

from app.pharmacy import router as pharmacy
from app.pharmacy.schemas import SupplierCreate
from app.users.models import Facility, User
from tests.pg_fixtures import db, engine  # noqa: F401  (list_suppliers is raw SQL; PostgreSQL only)

pytestmark = pytest.mark.asyncio


async def test_a_supplier_is_added_once_per_name(db):
    facility = Facility(id=uuid.uuid4(), name="Store DH", code=f"S{uuid.uuid4().hex[:5].upper()}", state_code="DL")
    db.add(facility)
    await db.flush()
    user = User(id=uuid.uuid4(), facility_id=facility.id, keycloak_sub=f"s-{uuid.uuid4().hex[:8]}",
                username=f"p-{uuid.uuid4().hex[:8]}", full_name="Pharmacist", is_active=True)
    db.add(user)
    await db.flush()
    caller = SimpleNamespace(id=user.id, facility_id=facility.id)
    first = await pharmacy.create_supplier_endpoint(SupplierCreate(name="  Shree  Medical "), current_user=caller, db=db)
    again = await pharmacy.create_supplier_endpoint(SupplierCreate(name="shree medical"), current_user=caller, db=db)
    assert (first.name, first.is_active, again.id) == ("Shree Medical", True, first.id)
    listed = await pharmacy.list_suppliers_endpoint(current_user=caller, db=db, include_inactive=False)
    assert [s.name for s in listed.items] == ["Shree Medical"]
