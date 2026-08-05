import base64
import os

# Must run before any app import — app.common.db calls get_settings() at
# module load time (app/main.py -> app/common/db.py), and Settings'
# _validate_aadhaar_keys (PR review blocker 1) refuses to boot without real
# keys. These are fixed, valid-shaped test keys — not the skip flag, since
# crypto-touching tests (blind index, encrypt/decrypt, blocker 8's dedup
# check) need real working keys, not a bypassed check.
os.environ.setdefault("AADHAAR_HMAC_KEY", "test-only-hmac-key-not-for-prod-use-0000")
os.environ.setdefault(
    "AADHAAR_ENCRYPTION_KEY",
    base64.b64encode(b"test-only-aes-key-32-bytes-longg").decode(),
)

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
