"""The local reference inventory must never execute or expose Postman secrets."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("collection_audit", Path(__file__).parents[1] / "check_abdm_collections.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_nested_requests_and_no_values_or_scripts_in_report(tmp_path):
    config = tmp_path / "config.py"
    config.write_text('class Settings:\n    abdm_path_test: str = "/v3/profile/login/verify"\n')
    collection = {"item": [{"item": [{"request": {
        "method": "POST", "url": "https://abhasbx.abdm.gov.in/abha/api/v3/profile/login/verify?token=DO-NOT-EMIT",
        "header": [{"key": "Authorization", "value": "DO-NOT-EMIT"}],
        "body": {"raw": "DO-NOT-EMIT"},
    }, "event": [{"script": {"exec": ["throw new Error('DO-NOT-EXECUTE')"]}}]}]}]}
    (tmp_path / "test.postman_collection.json").write_text(json.dumps(collection))
    result = audit.audit(tmp_path, config)
    assert result["requests"] == 1
    assert result["outbound_path_checks"]["abdm_path_test"]["in_supplied_collection"]
    assert "DO-NOT" not in json.dumps(result)


def test_missing_path_does_not_pass(tmp_path):
    config = tmp_path / "config.py"
    config.write_text('class Settings:\n    abdm_path_test: str = "/missing"\n')
    assert not audit.audit(tmp_path, config)["outbound_path_checks"]["abdm_path_test"]["in_supplied_collection"]


def test_abha_variable_expands_to_v3():
    assert audit.request_path({"url": "{{abha_url}}enrollment/request/otp"}) == "/v3/enrollment/request/otp"
