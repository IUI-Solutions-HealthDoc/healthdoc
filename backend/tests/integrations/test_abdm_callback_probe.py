"""Receiver diagnostics must never target NHA or a real pending operation."""

import io
import json
import uuid
from types import SimpleNamespace

import pytest

from scripts import probe_abdm_callback as probe


@pytest.mark.parametrize("url", ["http://localhost", "https://dev.abdm.gov.in", "https://example.com"])
def test_probe_refuses_other_destinations(url):
    with pytest.raises(ValueError, match="Only the HealthDoc"):
        probe.probe(base_url=url)


def test_local_probe_requires_trusted_certificate():
    with pytest.raises(ValueError, match="TLS"):
        probe.probe(base_url="https://localhost")


def test_probe_uses_only_synthetic_data_and_fresh_correlation_ids(monkeypatch):
    captured = []

    def open_request(request, timeout):
        captured.append(request)
        response = io.BytesIO(json.dumps({"error": {"message": {
            "code": "missing_abdm_headers" if len(captured) == 1 else "link_not_found",
            "detail": "private-response-value",
        }}}).encode())
        response.status = 400 if len(captured) == 1 else 404
        response.headers = {"X-HealthDoc-Receipt-ID": str(uuid.uuid4())}
        return response

    monkeypatch.setattr(probe, "get_settings", lambda: SimpleNamespace(abdm_hip_id="synthetic-hip"))
    monkeypatch.setattr(probe.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    results = probe.probe(base_url="https://abdm.healthdoc.world")
    assert len(results) == 2 and all(row["passed"] for row in results)
    assert [row["error_code"] for row in results] == ["missing_abdm_headers", "link_not_found"]
    assert "private-response-value" not in json.dumps(results)
    original_ids = []
    for request in captured:
        assert request.full_url == "https://abdm.healthdoc.world" + probe.CALLBACK
        assert request.method == "POST"
        body = json.loads(request.data)
        assert body["abhaAddress"] == "synthetic-receiver-probe@sbx"
        assert body["linkToken"] == "synthetic-not-issued"
        assert body["entity"] == "HIP" and body["error"] is None
        original_ids.append(uuid.UUID(body["response"]["requestId"]))
    assert len(set(original_ids)) == 2
    assert captured[0].get_header("Request-id") is None
    assert uuid.UUID(captured[1].get_header("Request-id")) not in original_ids


def test_probe_refuses_redirects_and_never_echoes_unknown_error_messages():
    assert probe.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.com") is None
    assert probe.safe_code({"error": {"message": "private-detail", "code": "private-code"}}) is None
