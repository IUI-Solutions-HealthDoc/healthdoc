"""HTTP-boundary regressions from the authenticated ZAP scan (#240)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.envelope import MAX_JSON_REQUEST_BYTES, EnvelopeMiddleware
from app.departments.schemas import DepartmentCreate, DepartmentUpdate, RoomCreate
from app.patients.schemas import PatientCreate, PatientSearchRequest


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(EnvelopeMiddleware)

    @app.get("/items")
    async def items(status: str | None = None) -> dict:
        return {"status": status}

    @app.post("/items")
    async def create_item(payload: dict) -> dict:
        return payload

    return TestClient(app)


def test_percent_encoded_nul_query_is_rejected_before_database() -> None:
    response = _client().get("/items?status=%00")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_control_character"


def test_json_escaped_nul_is_rejected_before_database() -> None:
    response = _client().post("/items", content=b'{"name":"bad\\u0000value"}', headers={
        "Content-Type": "application/json",
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_control_character"


def test_nested_json_key_with_nul_is_rejected() -> None:
    response = _client().post("/items", content=b'{"outer":{"bad\\u0000key":true}}', headers={
        "Content-Type": "application/json",
    })
    assert response.status_code == 400


def test_safe_json_is_replayed_unchanged_and_security_headers_are_present() -> None:
    response = _client().post("/items", json={"name": "safe"})
    assert response.status_code == 200
    assert response.json()["data"] == {"name": "safe"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-store"


def test_oversized_json_is_rejected_without_entering_route() -> None:
    response = _client().post("/items", json={"value": "x" * MAX_JSON_REQUEST_BYTES})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "json_body_too_large"


def test_department_code_rejects_zap_format_string_payload() -> None:
    try:
        DepartmentCreate(name="Emergency", code="ZAP%n%s")
    except ValueError as exc:
        assert "code" in str(exc)
    else:  # pragma: no cover - makes the failure explicit without pytest helpers
        raise AssertionError("format-string payload was accepted as a department code")


def test_department_inputs_are_normalised_and_bounded() -> None:
    department = DepartmentCreate(name="  Emergency Medicine  ", code="em-01")
    assert department.name == "Emergency Medicine"
    assert department.code == "EM-01"
    assert DepartmentUpdate(code="opd").code == "OPD"
    assert RoomCreate(department_id="00000000-0000-0000-0000-000000000001", room_number="A-12")


def test_malformed_aadhaar_is_rejected_before_blind_indexing() -> None:
    for schema, fields in (
        (PatientSearchRequest, {"aadhaar_number": "ZAP-invalid"}),
        (
            PatientCreate,
            {
                "full_name": "Test Patient",
                "sex": "female",
                "age_years": 30,
                "aadhaar_number": "1234-not-valid",
            },
        ),
    ):
        try:
            schema(**fields)
        except ValueError as exc:
            assert "aadhaar_number" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("malformed Aadhaar reached the blind-index layer")


def test_formatted_aadhaar_is_normalised_to_twelve_digits() -> None:
    request = PatientSearchRequest(aadhaar_number="1234-5678-9012")
    assert request.aadhaar_number == "123456789012"
