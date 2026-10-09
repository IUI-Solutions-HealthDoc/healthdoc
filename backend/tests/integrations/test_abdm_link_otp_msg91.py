"""The M2 linking OTP sent through MSG91 with the deployment's DLT template.

Template HEALTHDOC-OTP: "IUI Solutions: Your HealthDoc OTP is ##OTP##. Valid
for ##min## minutes. ..." The auth key comes from the environment; nothing
here is a real key or number.
"""

import json
import logging

import httpx
import pytest

from app.integrations.abdm.hip import link_otp

pytestmark = pytest.mark.asyncio
TEMPLATE = "69d8a5e5d27bf0b2c90c3e12"


class _Settings:
    environment = "dev"
    abdm_link_otp_sender = "msg91"
    abdm_link_otp_delivery_url = None
    abdm_link_otp_delivery_token = None
    msg91_auth_key = "synthetic-msg91-key"
    msg91_otp_template_id = TEMPLATE
    msg91_api = "flow"
    msg91_base_url = "https://msg91.test"


@pytest.fixture
def msg91(monkeypatch):
    settings, sent, answers = _Settings(), [], []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return answers.pop(0) if answers else httpx.Response(200, json={"type": "success", "message": "ok"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(link_otp, "get_settings", lambda: settings)
    monkeypatch.setattr(link_otp.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return settings, sent, answers


async def test_the_flow_api_fills_the_templates_otp_and_minutes(msg91):
    _, sent, _ = msg91
    await link_otp._deliver(mobile="+91-98765-43210", otp="482913")
    (request,) = sent
    assert str(request.url) == "https://msg91.test/api/v5/flow"
    assert request.headers["authkey"] == "synthetic-msg91-key"
    assert json.loads(request.content) == {
        "template_id": TEMPLATE, "short_url": "0",
        "recipients": [{"mobiles": "919876543210", "OTP": "482913", "min": "10"}],
    }


async def test_the_otp_api_carries_the_otp_as_its_parameter(msg91):
    settings, sent, _ = msg91
    settings.msg91_api = "otp"
    await link_otp._deliver(mobile="9876543210", otp="482913")
    (request,) = sent
    assert request.url.path == "/api/v5/otp"
    assert dict(request.url.params) == {
        "template_id": TEMPLATE, "mobile": "919876543210", "otp": "482913", "otp_expiry": "10"}
    assert json.loads(request.content) == {"min": "10"}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"type": "error", "message": "Invalid authkey"}),
        httpx.Response(401, json={"type": "error", "message": "Unauthorized"}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_anything_but_msg91_success_is_not_a_delivery(msg91, answer, caplog):
    _, _, answers = msg91
    answers.append(answer)
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(link_otp.LinkOtpUnavailable):
        await link_otp._deliver(mobile="9876543210", otp="482913")
    assert "482913" not in caplog.text and "9876543210" not in caplog.text


async def test_a_reason_msg91_echoes_is_logged_without_numbers(msg91, caplog):
    _, _, answers = msg91
    answers.append(httpx.Response(200, json={"type": "error", "message": "Mobile 919876543210 is in DND"}))
    with caplog.at_level(logging.WARNING, logger="healthdoc.abdm"), pytest.raises(link_otp.LinkOtpUnavailable):
        await link_otp._deliver(mobile="9876543210", otp="482913")
    assert "DND" in caplog.text and "9876543210" not in caplog.text


@pytest.mark.parametrize("mobile", ["+1 415 555 0100", "12345", "+91-1234567890"])
async def test_a_number_msg91_cannot_reach_is_refused_before_sending(msg91, mobile):
    _, sent, _ = msg91
    with pytest.raises(link_otp.LinkOtpUnavailable):
        await link_otp._deliver(mobile=mobile, otp="482913")
    assert sent == []


@pytest.mark.parametrize("missing", ["msg91_auth_key", "msg91_otp_template_id"])
async def test_msg91_without_its_key_or_template_sends_nothing(msg91, missing):
    settings, sent, _ = msg91
    setattr(settings, missing, None)
    with pytest.raises(link_otp.LinkOtpUnavailable, match="not configured"):
        await link_otp._deliver(mobile="9876543210", otp="482913")
    assert sent == []


async def test_the_relay_stays_the_default_sender(msg91):
    settings, sent, _ = msg91
    settings.abdm_link_otp_sender = "relay"
    with pytest.raises(link_otp.LinkOtpUnavailable, match="ABDM_LINK_OTP_DELIVERY_URL"):
        await link_otp._deliver(mobile="9876543210", otp="482913")
    assert sent == []
