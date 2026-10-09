"""M1 CRT_ABHA_301-309: ABHA from Aadhaar demographics (mandatory for government).

Shape from NHA's M1 Postman (18 Aug 2025), "BENEFIT_APIS > Demo Auth API":
POST enrol/byAadhaar with authMethods ["demo_auth"], LGD state/district codes
and a Benefit-Name header. The desk chooses LGD codes from the official list
the operator loaded; consent is NHA's published declaration (CRT_ABHA_302).
"""

import json

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.integrations.abdm.client import AbdmRejected, AbdmResponse
from app.integrations.abdm.identity import lgd, service
from app.patients.models import Patient
from scripts import import_lgd_districts
from tests.integrations.test_abdm_m1_identity_routes import AADHAAR, consent_for, desk  # noqa: F401

pytestmark = pytest.mark.asyncio

REFERENCE = {
    "states": {
        "27": {"name": "MAHARASHTRA", "districts": {"494": "SATARA", "490": "PUNE"}},
        "7": {"name": "DELHI", "districts": {"77": "NEW DELHI"}},
    }
}
PROFILE = {
    "healthIdNumber": "91-5006-4247-3341",
    "healthId": "91500642473341@sbx",
    "mobile": "******0903",
    "name": "Aarav Sharma",
    "yearOfBirth": "1990",
    "monthOfBirth": "5",
    "dayOfBirth": "17",
    "gender": "M",
    "kycVerified": True,
    "token": "synthetic-x-token",
}


class _Gateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, path, *, json=None, extra_headers=None, **kw):
        self.calls.append({"path": path, "json": json, "headers": dict(extra_headers or {})})
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return AbdmResponse(200, nxt, "req-id")


@pytest.fixture
def lgd_file(tmp_path, monkeypatch):
    path = tmp_path / "lgd.json"
    path.write_text(json.dumps(REFERENCE))

    class _Settings:
        abdm_lgd_reference_path = str(path)

    monkeypatch.setattr(lgd, "get_settings", lambda: _Settings())
    return path


@pytest.fixture
def demo(desk, lgd_file, monkeypatch):  # noqa: F811
    base = type(service.get_settings())

    class _S(base):
        abdm_benefit_name = "SYNTHETIC-PROGRAMME"

    monkeypatch.setattr(service, "get_settings", lambda: _S())
    gateway = _Gateway([PROFILE])
    monkeypatch.setattr(service, "get_abdm_client", lambda: gateway)
    desk["demo_gateway"] = gateway
    return desk


def _body(patient, **change):
    body = {
        "patient_id": str(patient.id), "aadhaar": AADHAAR, "name": "Aarav Sharma",
        "date_of_birth": "1990-05-17", "gender": "M", "mobile": "9876543210",
        "address": "12 Synthetic Lane", "pincode": "415001", "state_code": "27",
        "district_code": "494",
    }
    body.update(change)
    return body


async def _enrol(desk, **change):  # noqa: F811
    body = _body(desk["patient"], **change)
    body["consent"] = await consent_for(desk)
    return await desk["client"].post("/abdm/abha/enrol/demographic", json=body)


# ------------------------------------------------------------------ LGD


def test_lgd_reference_is_validated_and_listed_by_name(lgd_file):
    assert lgd.states() == [{"code": "7", "name": "DELHI"}, {"code": "27", "name": "MAHARASHTRA"}]
    assert [d["name"] for d in lgd.districts("27")] == ["PUNE", "SATARA"]
    assert lgd.require("27", "494") == ("MAHARASHTRA", "SATARA")
    with pytest.raises(lgd.LgdUnknown):
        lgd.require("27", "77"), "a district of another state is not this state's"
    with pytest.raises(lgd.LgdUnknown):
        lgd.districts("99")


def test_lgd_is_refused_when_not_loaded(monkeypatch):
    class _Unset:
        abdm_lgd_reference_path = None

    monkeypatch.setattr(lgd, "get_settings", lambda: _Unset())
    with pytest.raises(lgd.LgdUnavailable):
        lgd.states()


@pytest.mark.parametrize("bad", [{}, {"states": {}}, {"states": {"x": {"name": "A", "districts": {}}}},
                                 {"states": {"27": {"name": "", "districts": {}}}},
                                 {"states": {"27": {"name": "A", "districts": {"abc": "B"}}}}])
def test_a_malformed_reference_is_rejected(bad):
    with pytest.raises(ValueError):
        lgd.validate_reference(bad)


def test_importer_reads_the_official_export_by_its_column_titles(tmp_path):
    source = tmp_path / "districts.csv"
    source.write_text(
        "S.No.,State Code,State Name (In English),District Code,District Name (In English),Census 2011 Code\n"
        "1,27,MAHARASHTRA,494,SATARA,531\n2,27,MAHARASHTRA,490,PUNE,521\n3,7,DELHI,77,NEW DELHI,94\n",
        encoding="utf-8-sig",
    )
    reference = import_lgd_districts.convert(source)
    assert reference["states"] == REFERENCE["states"]


def test_importer_refuses_an_export_it_cannot_read_rather_than_guess(tmp_path):
    source = tmp_path / "other.csv"
    source.write_text("Code,Name\n27,MAHARASHTRA\n")
    with pytest.raises(SystemExit) as stopped:
        import_lgd_districts.convert(source)
    assert "Titles found" in str(stopped.value)
    clash = tmp_path / "clash.csv"
    clash.write_text("State Code,State Name,District Code,District Name\n27,A,1,X\n27,A,1,Y\n")
    with pytest.raises(SystemExit, match="two names"):
        import_lgd_districts.convert(clash)


def _hfr(monkeypatch, states, districts=None):
    from app.integrations.abdm.hfr import client as hfr

    asked = []

    async def lgd_states():
        return states

    async def lgd_districts(code):
        asked.append(code)
        return (districts or {}).get(code, [])

    monkeypatch.setattr(hfr, "lgd_states", lgd_states)
    monkeypatch.setattr(hfr, "lgd_districts", lgd_districts)
    return asked


async def test_importer_reads_the_same_lgd_codes_from_hfr(monkeypatch):
    asked = _hfr(
        monkeypatch,
        [
            {"code": "27", "name": "MAHARASHTRA", "districts": [
                {"code": "494", "name": "SATARA"}, {"code": "490", "name": "PUNE"}]},
            {"code": "7", "name": "DELHI"},
        ],
        {"7": [{"code": "77", "name": "NEW DELHI"}]},
    )
    reference = await import_lgd_districts.from_hfr()
    assert reference["states"] == REFERENCE["states"]
    assert asked == ["7"], "a state that came with its districts is not asked again"
    assert reference["source"] == "ABDM HFR /v1.5/facility/lgd"


@pytest.mark.parametrize(
    ("states", "message"),
    [
        ({"error": "unauthorised"}, "no state list"),
        ([{"code": "27", "name": "MAHARASHTRA"}], "no districts for state 27"),
        ([{"code": "27", "name": ""}], "without a code or name"),
        ([{"code": "27", "name": "A", "districts": [{"code": "1", "name": "X"}, {"code": "1", "name": "Y"}]}],
         "two names"),
    ],
)
async def test_an_hfr_answer_it_cannot_trust_stops_the_import(monkeypatch, states, message):
    _hfr(monkeypatch, states)
    with pytest.raises(SystemExit, match=message):
        await import_lgd_districts.from_hfr()


# ------------------------------------------------------------------ route


async def test_demographics_create_and_bind_the_abha(demo):
    response = await _enrol(demo)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["abha_number"] == "91-5006-4247-3341" and out["abha_address"] == "91500642473341@sbx"
    assert out["has_nha_card"] is True and out["date_of_birth"] == "17-05-1990"
    call = demo["demo_gateway"].calls[0]
    assert call["path"].endswith("/v3/enrollment/enrol/byAadhaar")
    assert call["headers"] == {"Benefit-Name": "SYNTHETIC-PROGRAMME"}
    sent = call["json"]
    assert sent["authData"]["authMethods"] == ["demo_auth"]
    demo_auth = sent["authData"]["demo_auth"]
    assert demo_auth["aadhaarNumber"] != AADHAAR, "the Aadhaar number is encrypted"
    assert {k: demo_auth[k] for k in ("stateCode", "districtCode", "dateOfBirth", "gender", "mobile", "pincode")} == {
        "stateCode": "27", "districtCode": "494", "dateOfBirth": "17-05-1990", "gender": "M",
        "mobile": "9876543210", "pincode": "415001",
    }
    assert sent["consent"] == {"code": "abha-enrollment", "version": "1.4"}
    db = demo["db"]
    patient = await db.get(Patient, demo["patient"].id)
    await db.refresh(patient)
    assert patient.abha_number == "91500642473341" and patient.abha_address == "91500642473341@sbx"
    assert patient.abha_linked_at is not None and patient.abha_profile_token_encrypted is not None
    row = (await db.execute(select(AuditLog).where(
        AuditLog.resource_type == "abha_enrolment_consent"))).scalar_one()
    assert row.new_value["method"] == "aadhaar_demographic"
    assert AADHAAR not in str(row.new_value) and AADHAAR not in response.text


@pytest.mark.parametrize(
    ("change", "code", "status"),
    [
        ({"state_code": "27", "district_code": "77"}, "lgd_code_unknown", 400),
        ({"state_code": "99", "district_code": "1"}, "lgd_code_unknown", 400),
    ],
)
async def test_codes_outside_the_lgd_list_never_reach_abdm(demo, change, code, status):
    response = await _enrol(demo, **change)
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert demo["demo_gateway"].calls == []


@pytest.mark.parametrize("aadhaar", ["12345", "1234567890123", "abcdefghijkl"])
async def test_an_invalid_aadhaar_number_is_refused_at_the_desk(demo, aadhaar):
    response = await _enrol(demo, aadhaar=aadhaar)
    assert response.status_code == 422
    assert demo["demo_gateway"].calls == []


async def test_details_that_do_not_match_aadhaar_create_nothing(demo):
    demo["demo_gateway"].responses = [AbdmRejected(400, {"code": "ABDM-1100"}, "rid")]
    response = await _enrol(demo)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "abha_demographics_rejected"
    patient = await demo["db"].get(Patient, demo["patient"].id)
    await demo["db"].refresh(patient)
    assert patient.abha_number is None


async def test_a_client_without_the_programme_role_is_a_gateway_refusal(demo):
    demo["demo_gateway"].responses = [AbdmRejected(403, {}, "rid")]
    response = await _enrol(demo)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "abdm_demographic_not_permitted"


async def test_no_benefit_name_means_no_call(desk, lgd_file, monkeypatch):  # noqa: F811
    base = type(service.get_settings())

    class _Unset(base):
        abdm_benefit_name = None

    monkeypatch.setattr(service, "get_settings", lambda: _Unset())
    gateway = _Gateway([PROFILE])
    monkeypatch.setattr(service, "get_abdm_client", lambda: gateway)
    response = await _enrol(desk)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "abdm_demographic_not_enabled"
    assert gateway.calls == []


async def test_the_lgd_list_must_be_loaded(demo, monkeypatch):
    class _Unset:
        abdm_lgd_reference_path = None

    monkeypatch.setattr(lgd, "get_settings", lambda: _Unset())
    states = await demo["client"].get("/abdm/abha/lgd/states")
    assert states.status_code == 409
    response = await _enrol(demo)
    assert response.status_code == 409 and demo["demo_gateway"].calls == []


async def test_desk_lists_states_and_districts(demo):
    states = await demo["client"].get("/abdm/abha/lgd/states")
    assert [s["code"] for s in states.json()["states"]] == ["7", "27"]
    districts = await demo["client"].get("/abdm/abha/lgd/districts", params={"state_code": "27"})
    assert [d["code"] for d in districts.json()["districts"]] == ["490", "494"]
    unknown = await demo["client"].get("/abdm/abha/lgd/districts", params={"state_code": "99"})
    assert unknown.status_code == 404


async def test_the_consent_confirmations_are_required(demo):
    body = _body(demo["patient"])
    body["consent"] = await consent_for(demo, beneficiary=False)
    response = await demo["client"].post("/abdm/abha/enrol/demographic", json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "enrolment_consent_refused"
    assert demo["demo_gateway"].calls == []


async def test_an_abha_already_on_another_chart_is_a_duplicate(demo):
    db = demo["db"]
    other = demo["other"]
    other.abha_number = "91500642473341"
    await db.commit()
    response = await _enrol(demo)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_abha"
