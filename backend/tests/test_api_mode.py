"""The control-room server serves the control room and nothing else.

Like BHAVYA's command centre on its own host, HEALTHDOC_API_MODE=control_room
must expose no clinical, financial or administrative route, and the hospitals'
API (hospital) must not serve the control room. The route set is pinned
exactly: a router added to the control-room server has to be argued for here.
Each mode is built in a fresh interpreter because main.py mounts at import.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _paths(mode: str) -> set[str]:
    out = subprocess.run(
        [sys.executable, "-c", "import json; from app.main import app; print(json.dumps(sorted(app.openapi()['paths'])))"],
        cwd=BACKEND, env={**os.environ, "API_MODE": mode, "PYTHONPATH": str(BACKEND)},
        capture_output=True, text=True, timeout=120, check=True,
    )
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def test_the_control_room_server_serves_exactly_the_control_room():
    assert _paths("control_room") == {
        "/api/v1/health",
        "/api/v1/health/deep",
        "/api/v1/audit/session/login",
        "/api/v1/audit/session/logout",
        "/api/v1/monitor/board",
        "/api/v1/monitor/trends",
        "/api/v1/monitor/facilities/{facility_id}",
        "/api/v1/monitor/facilities/{facility_id}/activity",
    }


@pytest.mark.parametrize("mode", ["hospital", "all"])
def test_the_hospital_api_keeps_its_routes_and_only_all_adds_the_control_room(mode):
    paths = _paths(mode)
    assert "/api/v1/patients/search" in paths and "/api/v1/audit/session/login" in paths
    has_monitor = any(path.startswith("/api/v1/monitor/") for path in paths)
    assert has_monitor is (mode == "all")


_BOOT = """
import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import configure_mappers
from app.main import app
with TestClient(app) as client:   # runs the lifespan: key checks, production auth guard, audit guard
    configure_mappers()           # every relationship resolves with only the control room imported
    print(json.dumps({
        "health": client.get("/api/v1/health").status_code,
        "board": client.get("/api/v1/monitor/board").status_code,
        "deep_checks": sorted(client.get("/api/v1/health/deep").json()["data"]["checks"]),
        "patients": client.get("/api/v1/patients/search").status_code,
    }))
"""


def _control_room_env(**overrides) -> dict:
    import certifi  # any valid CA bundle: these tests check wiring, not trust

    env = {
        **os.environ, "PYTHONPATH": str(BACKEND), "API_MODE": "control_room", "ENVIRONMENT": "production",
        "JWT_AUDIENCE": "healthdoc-backend",
        "JWT_ISSUER": "https://control.example/auth/realms/healthdoc-control",
        "JWT_JWKS_URL": "https://10.0.0.5:8443/auth/realms/healthdoc-control/protocol/openid-connect/certs",
        "JWT_JWKS_CA_FILE": certifi.where(),
        "DATABASE_SSL_CA_FILE": certifi.where(),
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def test_the_control_room_server_boots_in_production_with_only_its_modules():
    out = subprocess.run([sys.executable, "-c", _BOOT], cwd=BACKEND, env=_control_room_env(),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "health": 200, "board": 401, "patients": 404, "deep_checks": ["postgres"],
    }


@pytest.mark.parametrize("overrides, named", [
    ({"DATABASE_SSL_CA_FILE": None}, "DATABASE_SSL_CA_FILE"),
    ({"JWT_JWKS_CA_FILE": None}, "JWT_JWKS_URL"),
    ({"JWT_JWKS_URL": "http://10.0.0.5:8080/auth/realms/healthdoc-control/protocol/openid-connect/certs"}, "JWT_JWKS_URL"),
])
def test_the_control_room_server_refuses_plaintext_links_in_production(overrides, named):
    out = subprocess.run([sys.executable, "-c", _BOOT], cwd=BACKEND, env=_control_room_env(**overrides),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode != 0
    assert "Refusing to start in production" in out.stderr and named in out.stderr
