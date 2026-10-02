"""M1 VRFY_ABHA_301: the mobile ABHA lookup carries a CAPTCHA before any OTP."""

import base64

import pytest

from app.common import captcha
from tests.integrations.test_abdm_m1_identity_routes import desk  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def lookup(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(captcha, "get_redis", lambda: desk["redis"])
    return desk


async def _issued(desk):  # noqa: F811
    response = await desk["client"].get("/abdm/abha/captcha")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert base64.b64decode(body["image"].split(",", 1)[1]).startswith(b"\x89PNG")
    return body["captcha_id"]


def _answer_for(desk, captcha_id):  # noqa: F811
    import itertools

    digest = desk["redis"].store[captcha._key(captcha_id)]
    for letters in itertools.product(captcha.ALPHABET, repeat=captcha.LENGTH):
        if captcha._digest(captcha_id, "".join(letters)) == digest:
            return "".join(letters)
    raise AssertionError("no answer")


async def _request(desk, **extra):  # noqa: F811
    return await desk["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(desk["patient"].id), "mobile": "9876543210", **extra})


@pytest.mark.parametrize("extra", [{}, {"captcha_id": "never-issued", "captcha_answer": "ABCDE"}])
async def test_a_mobile_lookup_without_a_passed_captcha_sends_no_otp(lookup, extra):
    response = await _request(lookup, **extra)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "captcha_invalid"
    assert lookup["gateway"].calls == []


async def test_the_right_characters_let_the_lookup_through_once(lookup, monkeypatch):
    monkeypatch.setattr(captcha, "LENGTH", 2)  # keep the test's brute-force oracle quick
    lookup["gateway"].responses = [{"txnId": "mobile-txn"}, {"txnId": "mobile-txn-2"}]
    captcha_id = await _issued(lookup)
    answer = _answer_for(lookup, captcha_id)
    first = await _request(lookup, captcha_id=captcha_id, captcha_answer=answer.lower())
    assert first.status_code == 200, first.text
    assert len(lookup["gateway"].calls) == 1
    again = await _request(lookup, captcha_id=captcha_id, captcha_answer=answer)
    assert again.status_code == 400, "a challenge is spent by its first check"
    assert len(lookup["gateway"].calls) == 1


async def test_other_identifiers_need_no_captcha(lookup):
    lookup["gateway"].responses = [{"txnId": "number-txn"}]
    response = await lookup["client"].post("/abdm/abha/login/request-otp", json={
        "patient_id": str(lookup["patient"].id), "abha_number": "91-1111-2222-3333"})
    assert response.status_code == 200, response.text
