"""An ABHA refusal keeps ABDM's reason for the operator, never the values it echoes.

3 Oct 2026: a driving-licence enrolment came back 400 with no ABDM code, and
the log kept only `codes=[] fields=[]`, so the reason was lost.
"""

import logging

import pytest

from app.integrations.abdm.client import AbdmRejected
from app.integrations.abdm.identity import service

pytestmark = pytest.mark.asyncio


class _Refusing:
    def __init__(self, detail):
        self.detail = detail

    async def request(self, *args, **kwargs):
        raise AbdmRejected(400, self.detail, "synthetic-request")


@pytest.mark.parametrize(
    "detail",
    [
        {"message": "Invalid DL number UP1420190012345 for mobile 9876543210", "timestamp": "x"},
        {"error": {"message": "Invalid DL number 'UP1420190012345'", "code": "900"}},
    ],
)
async def test_the_reason_is_logged_without_the_licence_or_mobile(monkeypatch, caplog, detail):
    monkeypatch.setattr(service, "get_abdm_client", lambda: _Refusing(detail))
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(AbdmRejected):
        await service._post("/v3/enrollment/enrol/byDocument", {"documentId": "UP1420190012345"})
    assert "Invalid DL number" in caplog.text
    assert "json{" in caplog.text
    assert "1420190012345" not in caplog.text and "9876543210" not in caplog.text
