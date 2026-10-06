"""Two facilities of one deployment are two ABDM services, each addressed as itself.

The first speaks as ABDM_HIP_ID / ABDM_HIU_ID; each additional facility as its
HFR id. A callback reaches the facility NHA addressed, an id this bridge does not
serve reaches none, and nothing falls back to a default facility.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.integrations.abdm import external_router, facilities
from app.users.models import Facility
from tests.integrations.abdm_serving import serve

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def two(db, monkeypatch):
    first = Facility(id=uuid.uuid4(), code=f"A{uuid.uuid4().hex[:5]}", name="First Hospital",
                     state_code="MH", hfr_facility_id="IN-FIRST")
    second = Facility(id=uuid.uuid4(), code=f"B{uuid.uuid4().hex[:5]}", name="Second Hospital",
                      state_code="BR", hfr_facility_id="IN-SECOND")
    unlisted = Facility(id=uuid.uuid4(), code=f"C{uuid.uuid4().hex[:5]}", name="Not Linked",
                        state_code="BR", hfr_facility_id="IN-UNLISTED")
    db.add_all([first, second, unlisted])
    await db.flush()
    serve(monkeypatch, "IN-FIRST", hip="SBX-HIP", hiu="SBX-HIU", more="IN-SECOND")
    return first, second, unlisted


async def test_each_facility_goes_out_under_its_own_identity(db, two):
    first, second, unlisted = two
    assert await facilities.service_id_for(db, first.id, "hip") == "SBX-HIP"
    assert await facilities.service_id_for(db, first.id, "hiu") == "SBX-HIU"
    assert await facilities.service_id_for(db, second.id, "hip") == "IN-SECOND"
    assert await facilities.service_id_for(db, second.id, "hiu") == "IN-SECOND"
    with pytest.raises(facilities.FacilityNotServed):  # an HFR id alone is not a bridge link
        await facilities.service_id_for(db, unlisted.id, "hip")


async def test_a_callback_reaches_the_facility_it_addressed(db, two):
    first, second, _ = two
    assert await external_router._facility_id(db, "SBX-HIP", "hip") == first.id
    assert await external_router._facility_id(db, "SBX-HIU", "hiu") == first.id
    assert await external_router._facility_id(db, "IN-SECOND", "hip") == second.id
    assert await external_router._facility_id(db, "IN-SECOND", "hiu") == second.id


@pytest.mark.parametrize("service_id,role", [
    ("IN-UNLISTED", "hip"),  # has an HFR id, not linked to this bridge
    ("IN-FIRST", "hip"),     # the first facility's HFR id is not its HIP id
    ("SBX-HIU", "hip"),      # its HIU id is not its HIP id
    ("", "hiu"),
    (None, "hiu"),
])
async def test_an_id_this_bridge_does_not_serve_reaches_no_facility(db, two, service_id, role):
    with pytest.raises(HTTPException) as refused:
        await external_router._facility_id(db, service_id, role)
    assert refused.value.status_code == 404


def test_an_additional_id_that_clashes_with_another_facilitys_is_refused(monkeypatch):
    serve(monkeypatch, "IN-FIRST", hip="IN-SECOND", more="IN-SECOND")
    with pytest.raises(facilities.FacilityNotServed):
        facilities.served_ids("hip")


def test_the_served_hfr_ids_are_every_facility_listed(monkeypatch):
    serve(monkeypatch, "IN-FIRST", hip="SBX-HIP", more=" IN-SECOND , IN-THIRD ,")
    assert facilities.served_hfr_ids() == {"IN-FIRST", "IN-SECOND", "IN-THIRD"}
    assert facilities.served_ids("hip") == {"SBX-HIP", "IN-SECOND", "IN-THIRD"}
