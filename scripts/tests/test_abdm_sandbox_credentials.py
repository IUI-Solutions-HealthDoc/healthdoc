"""Execute the real sandbox helper with synthetic credentials and fake curl only."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "abdm_sandbox.sh"
SECRET = 'synthetic-secret-"quoted"-\\backslash'
TOKEN = "synthetic-bearer-not-a-real-token"


@pytest.fixture
def invoke(tmp_path):
    scripts, binaries = tmp_path / "scripts", tmp_path / "bin"
    scripts.mkdir()
    binaries.mkdir()
    shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
    (tmp_path / ".env").write_text(
        f"ABDM_CLIENT_ID=synthetic-test\nABDM_CLIENT_SECRET={shlex.quote(SECRET)}\n"
        "ABDM_GATEWAY_BASE_URL=https://gateway.test\n"
    )
    log = tmp_path / "fake-http.jsonl"
    curl = binaries / "curl"
    curl.write_text(f"#!{sys.executable}\n" + '''
import json,os,sys
args=sys.argv[1:]
incoming=sys.stdin.read()
with open(os.environ["FAKE_CURL_LOG"], "a") as handle:
    handle.write(json.dumps({"args":args,"stdin":incoming})+"\\n")
session=any(arg.endswith("/sessions") for arg in args)
key="SESSION" if session else "API"
print(os.environ["FAKE_"+key+"_BODY"])
print(os.environ["FAKE_"+key+"_STATUS"],end="")
sys.exit(int(os.environ.get("FAKE_"+key+"_EXIT","0")))
''')
    curl.chmod(0o700)
    uid = binaries / "uuidgen"
    uid.write_text("#!/bin/sh\nprintf '%s\\n' '11111111-2222-4333-8444-555555555555'\n")
    uid.chmod(0o700)

    def run(command="token", *args, **changes):
        env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
               "FAKE_CURL_LOG": str(log), "FAKE_SESSION_BODY": json.dumps({"accessToken": TOKEN}),
               "FAKE_SESSION_STATUS": "200", "FAKE_API_BODY": "[]", "FAKE_API_STATUS": "200",
               **changes}
        result = subprocess.run(["bash", str(scripts / SCRIPT.name), command, *args], env=env,
                                capture_output=True, text=True, timeout=10)
        requests = [json.loads(line) for line in log.read_text().splitlines()]
        return result, requests

    return run


def test_session_credentials_are_encoded_not_interpolated_or_written_to_disk(invoke):
    result, calls = invoke()
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert json.loads(calls[0]["stdin"]) == {
        "clientId": "synthetic-test", "clientSecret": SECRET, "grantType": "client_credentials",
    }
    assert "session token obtained" in result.stdout
    assert SECRET not in result.stdout + result.stderr and TOKEN not in result.stdout + result.stderr
    assert SECRET not in json.dumps(calls[0]["args"])
    assert "-o" not in calls[0]["args"] and "--output" not in calls[0]["args"]
    assert "--max-time" in calls[0]["args"]


@pytest.mark.parametrize("body,status,exit_code", [
    (json.dumps({"clientSecret": SECRET, "accessToken": TOKEN}), "401", "0"),
    (json.dumps({"accessToken": TOKEN}), "302", "0"),
    ("not-json-" + SECRET, "200", "0"),
    ("[]", "200", "0"), ("{}", "200", "0"),
    (json.dumps({"accessToken": True}), "200", "0"),
    (json.dumps({"accessToken": "line\nbreak"}), "200", "0"),
    (json.dumps({"accessToken": TOKEN}), "000", "28"),
])
def test_invalid_or_failed_session_cannot_leak_a_body_or_call_followup(invoke, body, status, exit_code):
    result, calls = invoke("services", FAKE_SESSION_BODY=body, FAKE_SESSION_STATUS=status,
                           FAKE_SESSION_EXIT=exit_code)
    assert result.returncode != 0
    assert len(calls) == 1
    assert SECRET not in result.stdout + result.stderr and TOKEN not in result.stdout + result.stderr
    assert "session token obtained" not in result.stdout


def test_authenticated_call_keeps_bearer_out_of_process_arguments(invoke):
    result, calls = invoke("services")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert TOKEN not in json.dumps([call["args"] for call in calls])
    assert calls[1]["stdin"] == f"Authorization: Bearer {TOKEN}\n"
    assert "@-" in calls[1]["args"]
    assert TOKEN not in result.stdout + result.stderr
    assert "[HTTP 200]" in result.stdout


@pytest.mark.parametrize("status,exit_code", [("403", "0"), ("502", "0"), ("302", "0"), ("000", "28")])
def test_authenticated_failure_never_prints_upstream_body_or_claims_success(invoke, status, exit_code):
    result, calls = invoke("services", FAKE_API_STATUS=status, FAKE_API_EXIT=exit_code,
                           FAKE_API_BODY=json.dumps({"echo": SECRET, "token": TOKEN}))
    assert result.returncode != 0
    assert len(calls) == 2
    assert SECRET not in result.stdout + result.stderr and TOKEN not in result.stdout + result.stderr
    assert "[HTTP " not in result.stdout


def test_bridge_patch_keeps_json_body_separate_from_stdin_headers(invoke):
    address = "https://callback.test/quoted-\"path"
    result, calls = invoke("set-url", address, FAKE_API_STATUS="202", FAKE_API_BODY="")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 4  # Session + PATCH, then a new session + GET read-back.
    request = calls[1]
    assert request["args"][request["args"].index("-X") + 1] == "PATCH"
    assert json.loads(request["args"][request["args"].index("--data") + 1]) == {"url": address}
    assert request["stdin"] == f"Authorization: Bearer {TOKEN}\n"
    assert TOKEN not in json.dumps([call["args"] for call in calls])


def test_failed_bridge_patch_stops_before_readback(invoke):
    result, calls = invoke("set-url", "https://callback.test", FAKE_API_STATUS="403")
    assert result.returncode != 0
    assert len(calls) == 2
    assert "read-back" not in result.stdout
