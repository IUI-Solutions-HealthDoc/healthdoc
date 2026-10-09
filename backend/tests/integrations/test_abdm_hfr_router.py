"""ABDM M4 HFR: search (HFR-001 to 009), master data and bridge linkage (HFR-118 to 123).

The HFR transport is replaced; these assert what HealthDoc sends and refuses.
Shapes are NHA's M4 Postman collection and a live sandbox search on 2 Oct 2026.
"""

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.auth.deps import AuthUser, get_current_user
from app.integrations.abdm.client import AbdmAuthError, AbdmRejected
from app.integrations.abdm.hfr import client
from app.integrations.abdm.hfr import router as hfr_router

pytestmark = pytest.mark.asyncio

FOUND = {
    "message": "Request processed successfully", "totalFacilities": 1, "numberOfPages": 1,
    "facilities": [{"facilityId": "IN0910034387", "facilityName": "HealthDoc Facility",
                    "facilityStatus": "Submitted", "ownershipCode": "G", "stateLGDCode": "9"}],
}


class _Hfr:
    def __init__(self):
        self.calls = []
        self.answers = {}

    async def call(self, method, path, *, json=None, headers=None):
        self.calls.append((method, path, json))
        answer = self.answers.get(path.split("?")[0])
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest_asyncio.fixture
async def hfr(monkeypatch):
    fake = _Hfr()
    monkeypatch.setattr(client, "call", fake.call)

    class _S:
        abdm_client_id = "SBXID_TEST"

    monkeypatch.setattr(hfr_router, "get_settings", lambda: _S())
    app = FastAPI()
    app.include_router(hfr_router.router)
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub="admin-sub", roles=["admin"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield fake, http, app


async def test_search_by_facility_id_sends_only_the_id_with_fixed_paging(hfr):
    fake, http, _ = hfr
    fake.answers["/FacilityManagement/v1.5/facility/search"] = FOUND
    response = await http.post("/abdm/hfr/facilities/search", json={"facility_id": "IN0910034387"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and response.json()["pages"] == 1
    sent = fake.calls[0][2]
    assert sent["facilityId"] == "IN0910034387" and sent["facilityName"] == ""
    assert (sent["page"], sent["resultsPerPage"]) == ("1", "10")


@pytest.mark.parametrize("bad", ["0910034387", "IN09100343", "IN0910034387X", "XX0910034387", "in0910034387"])
async def test_a_facility_id_must_be_12_characters_starting_in(hfr, bad):
    fake, http, _ = hfr
    response = await http.post("/abdm/hfr/facilities/search", json={"facility_id": bad})
    assert response.status_code == 422 and fake.calls == []


@pytest.mark.parametrize("missing", ["facility_name", "ownership_code", "state_lgd_code"])
async def test_without_an_id_name_ownership_and_state_are_required(hfr, missing):
    fake, http, _ = hfr
    body = {"facility_name": "hospital", "ownership_code": "G", "state_lgd_code": "27"}
    del body[missing]
    response = await http.post("/abdm/hfr/facilities/search", json=body)
    assert response.status_code == 422 and fake.calls == []


async def test_a_name_search_passes_the_narrowing_fields_and_page(hfr):
    fake, http, _ = hfr
    fake.answers["/FacilityManagement/v1.5/facility/search"] = {"facilities": []}
    response = await http.post("/abdm/hfr/facilities/search", json={
        "facility_name": "District Hospital", "ownership_code": "G", "state_lgd_code": "27",
        "district_lgd_code": "494", "pincode": "415001", "page": 2,
    })
    assert response.status_code == 200
    sent = fake.calls[0][2]
    assert sent == {
        "facilityId": "", "facilityName": "District Hospital", "ownershipCode": "G",
        "stateLGDCode": "27", "districtLGDCode": "494", "subDistrictLGDCode": "",
        "pincode": "415001", "page": "2", "resultsPerPage": "10",
    }


@pytest.mark.parametrize("body", [
    {"facility_name": "Hosp<script>", "ownership_code": "G", "state_lgd_code": "27"},
    {"facility_name": "Hospital", "ownership_code": "G", "state_lgd_code": "27", "pincode": "1234567"},
])
async def test_name_and_pincode_rules(hfr, body):
    fake, http, _ = hfr
    assert (await http.post("/abdm/hfr/facilities/search", json=body)).status_code == 422


async def test_bridge_link_fetches_the_name_and_uses_this_bridge(hfr):
    fake, http, _ = hfr
    fake.answers["/FacilityManagement/v1.5/facility/search"] = FOUND
    fake.answers["/v1/bridges/MutipleHRPAddUpdateServices"] = {"message": "ok"}
    response = await http.post("/abdm/hfr/bridge-link", json={
        "facility_id": "IN0910034387",
        "services": [{"type": "HIP", "hip_name": "HealthDoc Facility HIP"},
                     {"type": "HIU", "hip_name": "HealthDoc Facility HIU", "active": False}],
    })
    assert response.status_code == 200, response.text
    method, path, sent = fake.calls[-1]
    assert (method, path) == ("POST", "/v1/bridges/MutipleHRPAddUpdateServices")
    assert sent == {
        "facilityId": "IN0910034387", "facilityName": "HealthDoc Facility",
        "HRP": [
            {"bridgeId": "SBXID_TEST", "hipName": "HealthDoc Facility HIP", "type": "HIP", "active": True},
            {"bridgeId": "SBXID_TEST", "hipName": "HealthDoc Facility HIU", "type": "HIU", "active": False},
        ],
    }


async def test_bridge_link_refuses_an_id_hfr_does_not_know(hfr):
    fake, http, _ = hfr
    fake.answers["/FacilityManagement/v1.5/facility/search"] = {"facilities": []}
    response = await http.post("/abdm/hfr/bridge-link", json={
        "facility_id": "IN0910034387", "services": [{"type": "HIP", "hip_name": "X"}]})
    assert response.status_code == 404
    assert all(path != "/v1/bridges/MutipleHRPAddUpdateServices" for _, path, _ in fake.calls)


@pytest.mark.parametrize("services", [[], [{"type": "HIP", "hip_name": "A"}, {"type": "HIP", "hip_name": "B"}],
                                      [{"type": "HRP", "hip_name": "A"}], [{"type": "HIP", "hip_name": ""}]])
async def test_bridge_services_are_one_named_hip_or_hiu_each(hfr, services):
    fake, http, _ = hfr
    response = await http.post("/abdm/hfr/bridge-link", json={"facility_id": "IN0910034387", "services": services})
    assert response.status_code == 422 and fake.calls == []


async def test_master_and_lgd_lists_are_passed_through_in_one_shape(hfr):
    fake, http, _ = hfr
    fake.answers["/v1.5/facility/get-master-data"] = {"type": "OWNER", "data": [{"code": "G", "value": "Government"}]}
    fake.answers["/v1.5/facility/lgd/states"] = [{"code": "27", "name": "Maharashtra", "districts": [{"code": "494"}]}]
    fake.answers["/v1.5/facility/lgd/districts"] = [{"code": "494", "name": "Satara"}]
    owner = await http.get("/abdm/hfr/master/OWNER")
    assert owner.json() == {"type": "OWNER", "data": [{"code": "G", "value": "Government"}]}
    assert fake.calls[-1][1] == "/v1.5/facility/get-master-data?type=OWNER"
    states = await http.get("/abdm/hfr/lgd/states")
    assert states.json() == {"states": [{"code": "27", "name": "Maharashtra"}]}
    districts = await http.get("/abdm/hfr/lgd/districts", params={"state_code": "27"})
    assert districts.json()["districts"][0]["code"] == "494"
    assert (await http.get("/abdm/hfr/master/owner;drop")).status_code == 422
    assert (await http.get("/abdm/hfr/lgd/districts", params={"state_code": "27&x=1"})).status_code == 422


async def test_hfr_refusals_name_hfr_and_never_echo_its_body(hfr):
    fake, http, _ = hfr
    fake.answers["/v1.5/facility/get-master-types"] = AbdmRejected(400, {"echo": "secret"}, "rid")
    response = await http.get("/abdm/hfr/master-types")
    assert response.status_code == 502 and "secret" not in response.text
    fake.answers["/v1.5/facility/get-master-types"] = AbdmAuthError("refused")
    response = await http.get("/abdm/hfr/master-types")
    assert response.json()["detail"]["code"] == "hfr_not_permitted"


async def test_only_the_admin_reaches_hfr(hfr):
    fake, http, app = hfr
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub="desk", roles=["receptionist"])
    assert (await http.get("/abdm/hfr/master-types")).status_code == 403
    assert fake.calls == []
