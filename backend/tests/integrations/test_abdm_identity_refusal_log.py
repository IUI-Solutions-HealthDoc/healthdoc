"""An ABHA refusal keeps ABDM's reason for the operator, never the values it echoes.

3 Oct 2026: a driving-licence enrolment came back 400 with no ABDM code, and
the log kept only `codes=[] fields=[]`, so the reason was lost.
"""

import logging

import pytest

from app.integrations.abdm.client import AbdmRejected, AbdmUnavailable
from app.integrations.abdm.identity import service

pytestmark = pytest.mark.asyncio


class _Refusing:
    def __init__(self, detail):
        self.detail = detail

    async def request(self, *args, **kwargs):
        raise AbdmRejected(400, self.detail, "synthetic-request")


async def test_a_licence_field_refusal_is_logged_without_the_values(monkeypatch, caplog):
    detail = {
        "Dob": "Invalid DOB 06-08-2000",
        "FrontSidePhoto": "Please upload a document of size less than 150KB.",
        "timestamp": "2026-10-03 15:40:01",
    }
    monkeypatch.setattr(service, "get_abdm_client", lambda: _Refusing(detail))
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(AbdmRejected):
        await service._post("/v3/enrollment/enrol/byDocument", {"dob": "2000-08-06"})
    assert "Dob: Invalid DOB" in caplog.text and "less than 150KB" in caplog.text
    assert "json{Dob,FrontSidePhoto,timestamp}" in caplog.text
    assert "06-08-2000" not in caplog.text


@pytest.mark.parametrize(
    "detail",
    [
        {"message": "Name RITIK KUMAR and DL UP1420190012345 do not match", "code": "ABDM-1203"},
        {"FirstName": "RITIK is not on the licence", "loginId": "someone@sbx"},
    ],
)
async def test_free_text_and_identity_fields_are_never_logged(monkeypatch, caplog, detail):
    monkeypatch.setattr(service, "get_abdm_client", lambda: _Refusing(detail))
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(AbdmRejected):
        await service._post("/v3/enrollment/enrol/byDocument", {})
    for private in ("RITIK", "KUMAR", "1420190012345", "someone@sbx"):
        assert private not in caplog.text


async def test_a_refused_mobile_keeps_the_reason_without_the_number(monkeypatch, caplog):
    # byAadhaar names the communication mobile it refused (live, 6 Oct 2026).
    detail = {"mobile": "Invalid mobile number 9876543210", "timestamp": "2026-10-06 19:20:54"}
    monkeypatch.setattr(service, "get_abdm_client", lambda: _Refusing(detail))
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(AbdmRejected):
        await service._post("/v3/enrollment/enrol/byAadhaar", {})
    assert "mobile: Invalid mobile number" in caplog.text
    assert "9876543210" not in caplog.text


class _Down:
    async def request(self, *args, **kwargs):
        raise AbdmUnavailable(
            "ABDM request unavailable", status_code=504, stage="request",
            error_codes=("ABDM-1206",), body_shape="json{error{code,message}}",
            safe_message="Aadhaar Gateway is unavailable",
        )


async def test_an_outage_is_logged_with_its_status_code_and_reason(monkeypatch, caplog):
    # A 5xx reached the desk as "temporarily unavailable" with nothing logged.
    monkeypatch.setattr(service, "get_abdm_client", lambda: _Down())
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(AbdmUnavailable):
        await service._post("/v3/enrollment/request/otp", {"loginId": "sealed"})
    assert "status=504" in caplog.text and "ABDM-1206" in caplog.text
    assert "Aadhaar Gateway is unavailable" in caplog.text
    assert "sealed" not in caplog.text
