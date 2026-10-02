"""The facility manager's HPR login that HFR registration requires (ABDM M4).

Shapes from NHA's M4 Postman: auth/init then confirmWithAadhaarOtp, or
authPassword. The token is the professional's credential: kept encrypted
server-side for this admin only, never returned, capped at 30 minutes.
"""

import base64
import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.auth.deps import AuthUser, DbUser, get_current_db_user, get_current_user
from app.integrations.abdm.hfr import client, hpr_login
from app.integrations.abdm.hfr import router as hfr_router

pytestmark = pytest.mark.asyncio
FACILITY, ADMIN = uuid.uuid4(), uuid.uuid4()


def _jwt(**claims) -> str:
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS512'})}.{part(claims)}.signature"


class _Redis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def get(self, key):
        found = self.store.get(key)
        return found[0] if found else None

    async def delete(self, key):
        self.store.pop(key, None)


class _Hpr:
    def __init__(self):
        self.calls = []
        self.answers = {}

    async def call(self, method, path, *, json=None, headers=None):
        self.calls.append((method, path, json, headers))
        return self.answers.get(path)


@pytest_asyncio.fixture
async def hpr(monkeypatch):
    redis, fake = _Redis(), _Hpr()
    monkeypatch.setattr(hpr_login, "get_redis", lambda: redis)
    monkeypatch.setattr(client, "call", fake.call)
    app = FastAPI()
    app.include_router(hfr_router.router)
    caller = DbUser(id=ADMIN, keycloak_sub="admin-sub", username="admin", facility_id=FACILITY, roles=["admin"])
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub="admin-sub", roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        yield fake, redis, http, app


async def _otp_login(fake, http, token):
    fake.answers["/api/v1/auth/init"] = {"transactionId": "txn-1", "mobileNumber": "******1234"}
    fake.answers["/api/v1/auth/confirmWithAadhaarOtp"] = {"token": token}
    started = await http.post("/abdm/hfr/hpr-login/otp", json={"hpr_id": "kumar682000@hpr.abdm", "method": "AADHAAR_OTP"})
    assert started.status_code == 200, started.text
    assert started.json()["masked_mobile"] == "******1234"
    return await http.post("/abdm/hfr/hpr-login/verify", json={"session_id": started.json()["session_id"], "otp": "123456"})


async def test_aadhaar_otp_login_keeps_the_token_server_side_only(hpr):
    fake, redis, http, _ = hpr
    token = _jwt(hprId="kumar682000@hpr.abdm", hprIdNumber="71-0000-0000-0001", exp=int(time.time()) + 600)
    verified = await _otp_login(fake, http, token)
    assert verified.status_code == 200, verified.text
    assert verified.json() == {"logged_in": True, "hpr_id": "kumar682000@hpr.abdm",
                               "hpr_id_number": "71-0000-0000-0001", "expires_at": verified.json()["expires_at"]}
    assert token not in verified.text
    assert fake.calls[0][2] == {"idType": "", "domainName": "", "authMethod": "AADHAAR_OTP", "hprId": "kumar682000@hpr.abdm"}
    assert fake.calls[1][2] == {"otp": "123456", "txnId": "txn-1"}
    (sealed, ttl), = [v for k, v in redis.store.items() if k.startswith("hfr:hpr-token:")]
    assert token not in sealed and "kumar682000" not in sealed
    assert 0 < ttl <= 600
    state = await http.get("/abdm/hfr/hpr-login")
    assert state.json()["logged_in"] is True and token not in state.text


async def test_a_long_lived_token_is_kept_for_thirty_minutes_at_most(hpr):
    fake, redis, http, _ = hpr
    await _otp_login(fake, http, _jwt(hprId="kumar682000@hpr.abdm", exp=int(time.time()) + 86400))
    (_, ttl), = [v for k, v in redis.store.items() if k.startswith("hfr:hpr-token:")]
    assert ttl <= hpr_login.MAX_TOKEN_TTL


@pytest.mark.parametrize("hpr_id", ["kumar682000", "x@hpr.abdm", "kumar@abdm", "71-0000-0000", "<script>@hpr.abdm"])
async def test_an_hpr_id_must_look_like_one(hpr, hpr_id):
    fake, _, http, _ = hpr
    response = await http.post("/abdm/hfr/hpr-login/otp", json={"hpr_id": hpr_id, "method": "AADHAAR_OTP"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "hpr_id_invalid"
    assert fake.calls == []


async def test_mobile_otp_is_not_offered(hpr):
    """init + confirmWithMobileOTP answered 503 live on 2 October; NHA's mobile
    login is a separate v2 flow this module does not implement."""
    fake, _, http, _ = hpr
    response = await http.post(
        "/abdm/hfr/hpr-login/otp", json={"hpr_id": "kumar682000@hpr.abdm", "method": "MOBILE_OTP"})
    assert response.status_code == 422
    assert fake.calls == []


async def test_a_login_session_belongs_to_the_admin_who_started_it(hpr):
    fake, redis, http, app = hpr
    fake.answers["/api/v1/auth/init"] = {"transactionId": "txn-1"}
    started = await http.post("/abdm/hfr/hpr-login/otp", json={"hpr_id": "kumar682000@hpr.abdm", "method": "AADHAAR_OTP"})
    other = DbUser(id=uuid.uuid4(), keycloak_sub="other", username="other", facility_id=FACILITY, roles=["admin"])
    app.dependency_overrides[get_current_db_user] = lambda: other
    response = await http.post("/abdm/hfr/hpr-login/verify", json={"session_id": started.json()["session_id"], "otp": "123456"})
    assert response.status_code == 404
    assert all(path != "/api/v1/auth/confirmWithAadhaarOtp" for _, path, _, _ in fake.calls)


async def test_a_refused_otp_returns_no_token_and_keeps_nothing(hpr):
    fake, redis, http, _ = hpr
    verified = await _otp_login(fake, http, None)
    assert verified.status_code == 400 and verified.json()["detail"]["code"] == "hpr_login_failed"
    assert not any(k.startswith("hfr:hpr-token:") for k in redis.store)


async def test_password_login_never_echoes_the_password(hpr):
    fake, _, http, _ = hpr
    fake.answers["/api/v1/auth/authPassword"] = {"token": _jwt(hprId="kumar682000@hpr.abdm", exp=int(time.time()) + 600)}
    response = await http.post("/abdm/hfr/hpr-login/password", json={"hpr_id": "kumar682000@hpr.abdm", "password": "S3cret!pw"})
    assert response.status_code == 200 and "S3cret" not in response.text
    assert fake.calls[0][2]["password"] == "S3cret!pw"


async def test_logout_forgets_the_token_and_tells_hpr(hpr):
    fake, redis, http, _ = hpr
    token = _jwt(hprId="kumar682000@hpr.abdm", exp=int(time.time()) + 600)
    await _otp_login(fake, http, token)
    response = await http.delete("/abdm/hfr/hpr-login")
    assert response.json() == {"logged_in": False}
    assert not any(k.startswith("hfr:hpr-token:") for k in redis.store)
    assert fake.calls[-1][:2] == ("GET", "/v4/auth/logout") and fake.calls[-1][3] == {"Authorization": token}
    assert (await http.get("/abdm/hfr/hpr-login")).json() == {"logged_in": False}


async def test_only_the_admin_logs_in_to_hpr(hpr):
    fake, _, http, app = hpr
    app.dependency_overrides[get_current_user] = lambda: AuthUser(sub="desk", roles=["receptionist"])
    response = await http.post("/abdm/hfr/hpr-login/otp", json={"hpr_id": "kumar682000@hpr.abdm", "method": "AADHAAR_OTP"})
    assert response.status_code == 403 and fake.calls == []
