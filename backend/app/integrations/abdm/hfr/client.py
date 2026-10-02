"""HFR v4 calls, shaped from NHA's M4 Postman collection (NHPR-SBX-Api).

Every call carries the ordinary gateway session token. HFR answers with plain
JSON (not the gateway's async callback pattern), so each function returns the
parsed body or raises the client's error; nothing here retries a write.
"""

from __future__ import annotations

from typing import Any

from app.common.config import get_settings
from app.integrations.abdm.client import AbdmResponse, get_abdm_client


async def call(method: str, path: str, *, json: dict | None = None) -> Any:
    url = f"{get_settings().abdm_hfr_base_url.rstrip('/')}{path}"
    response: AbdmResponse = await get_abdm_client().request(method, url, json=json)
    return response.body


async def master_types() -> Any:
    return await call("GET", "/v1.5/facility/get-master-types")


async def master_data(kind: str) -> Any:
    return await call("GET", f"/v1.5/facility/get-master-data?type={kind}")


async def lgd_states() -> Any:
    return await call("GET", "/v1.5/facility/lgd/states")


async def lgd_districts(state_code: str) -> Any:
    return await call("GET", f"/v1.5/facility/lgd/districts?stateCode={state_code}")


async def lgd_subdistricts(district_code: str) -> Any:
    return await call("GET", f"/v1.5/facility/lgd/subdistricts?districtCode={district_code}")


async def facility_types(ownership_code: str, system_of_medicine_code: str) -> Any:
    return await call(
        "POST",
        "/v1.5/facility/fetch-facility-type",
        json={"ownershipCode": ownership_code, "systemOfMedicineCode": system_of_medicine_code},
    )


async def facility_subtypes(facility_type_code: str) -> Any:
    return await call(
        "POST", "/v1.5/facility/fetch-facility-Sub-type", json={"facilityTypeCode": facility_type_code}
    )


async def owner_subtypes(ownership_code: str, owner_subtype_code: str | None) -> Any:
    body = {"ownershipCode": ownership_code}
    if owner_subtype_code:
        body["ownerSubtypeCode"] = owner_subtype_code
    return await call("POST", "/v1.5/facility/get-owner-subtype", json=body)


async def specialities(system_of_medicine_code: str) -> Any:
    return await call(
        "POST", "/v1.5/facility/get-specialities", json={"systemOfMedicineCode": system_of_medicine_code}
    )


async def search_facilities(criteria: dict[str, str]) -> Any:
    return await call("POST", "/FacilityManagement/v1.5/facility/search", json=criteria)


async def link_bridge(facility_id: str, facility_name: str, services: list[dict]) -> Any:
    return await call(
        "POST",
        "/v1/bridges/MutipleHRPAddUpdateServices",
        json={"facilityId": facility_id, "facilityName": facility_name, "HRP": services},
    )
