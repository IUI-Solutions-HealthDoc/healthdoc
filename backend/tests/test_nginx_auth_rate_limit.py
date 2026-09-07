"""Login assets must not exhaust the credential-request rate-limit bucket."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NGINX = ROOT / "infra/nginx"


def auth_map():
    config = (NGINX / "nginx.conf").read_text()
    block = re.search(
        r'map "\$request_method:\$uri" \$healthdoc_auth_limit_key \{([^}]+)\}', config
    )
    assert block, "Auth rate limiting must distinguish read-only theme assets from credentials"
    assert "default $binary_remote_addr;" in block[1]
    return re.findall(r'~(\S+)\s+"";', block[1])


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_read_only_theme_assets_do_not_spend_the_login_budget(method):
    key = f"{method}:/auth/resources/version/login/healthdoc/css/login.css"
    assert any(re.search(pattern, key) for pattern in auth_map())


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("step", [1, 2])
def test_read_only_cookie_probe_pages_do_not_spend_the_login_budget(method, step):
    key = f"{method}:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies/step{step}.html"
    assert any(re.search(pattern, key) for pattern in auth_map())


@pytest.mark.parametrize("key", [
    "POST:/auth/realms/healthdoc/login-actions/authenticate",
    "POST:/auth/realms/healthdoc/protocol/openid-connect/token",
    "GET:/auth/realms/healthdoc/protocol/openid-connect/auth",
    "POST:/auth/resources/version/login/healthdoc/css/login.css",
    "GET:/auth/resources-pretend/login.css",
    "GET:/auth/admin/realms/healthdoc/users",
    "POST:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies/step1.html",
    "POST:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies/step2.html",
    "GET:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies/step3.html",
    "GET:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies/step1.html/token",
    "GET:/auth/realms/healthdoc/protocol/openid-connect/3p-cookies-pretend/step1.html",
    "GET:/auth/realms/healthdoc/protocol/openid-connect/token",
])
def test_credentials_and_non_asset_requests_remain_limited(key):
    assert not any(re.search(pattern, key) for pattern in auth_map())


def test_auth_zone_uses_the_scoped_key_without_increasing_credential_rate():
    config = (NGINX / "nginx.conf").read_text()
    assert "limit_req_zone $healthdoc_auth_limit_key zone=auth:10m rate=10r/s;" in config
    for relative in ("conf.d/healthdoc.conf", "prod-conf.d/healthdoc.conf"):
        location = (NGINX / relative).read_text().split("location /auth/ {", 1)[1].split("\n    }", 1)[0]
        assert "limit_req zone=auth burst=20 nodelay;" in location
        assert "limit_req_dry_run on" not in location
