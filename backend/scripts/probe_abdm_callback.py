"""Synthetic local/public receiver probes; never request a token from NHA.

Each request uses freshly random callback AND operation IDs. An unknown operation
must return 404, not be accepted. No real ABHA, token, operation ID or payload input
is accepted by this tool. A successful matched-operation replay belongs in the
isolated regression database, never in the participant's live pending operation.
"""

import argparse
import json
import ssl
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.common.config import get_settings

CALLBACK = "/api/v3/hip/token/on-generate-token"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_code(value):
    """Only the expected refusal vocabulary; never echo response messages."""
    if isinstance(value, dict):
        code = value.get("code")
        if code in ("link_not_found", "missing_abdm_headers", "unknown_service",
                    "invalid_timestamp", "invalid_request_id", "abdm_hfr_not_seeded"):
            return code
        for key in ("error", "detail", "message"):
            result = safe_code(value.get(key))
            if result:
                return result
    return None


def probe(*, base_url: str, ca_cert: Path | None = None):
    if base_url not in {"https://localhost", "https://abdm.healthdoc.world"}:
        raise ValueError("Only the HealthDoc local or registered public receiver is allowed")
    if base_url == "https://localhost" and ca_cert is None:
        raise ValueError("Local TLS requires the explicitly trusted development certificate")
    hip_id = get_settings().abdm_hip_id
    if not hip_id or hip_id == "change-me":
        raise ValueError("Configure ABDM_HIP_ID; no credential fallback is allowed")
    context = ssl.create_default_context(cafile=str(ca_cert) if ca_cert else None)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())
    results = []
    for case, expected in (("missing_headers", 400), ("wrapper_unknown_operation", 404)):
        rid, original = str(uuid.uuid4()), str(uuid.uuid4())
        payload = {"abhaAddress": "synthetic-receiver-probe@sbx",
                   "linkToken": "synthetic-not-issued", "response": {"requestId": original},
                   "error": None, "entity": "HIP"}
        headers = {"Content-Type": "application/json", "User-Agent": "HealthDoc-Synthetic-Receiver-Probe/1.0"}
        if case != "missing_headers":
            headers.update({"REQUEST-ID": rid, "TIMESTAMP": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "X-HIP-ID": hip_id})
        request = urllib.request.Request(base_url + CALLBACK, data=json.dumps(payload).encode(),
                                         method="POST", headers=headers)
        try:
            response = opener.open(request, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read(16 * 1024)
            try:
                code = safe_code(json.loads(body))
            except (ValueError, RecursionError):
                code = None
            results.append({"case": case, "status": response.status, "expected_status": expected,
                            "passed": response.status == expected, "error_code": code,
                            "receipt_id": response.headers.get("X-HealthDoc-Receipt-ID"),
                            "synthetic_request_id": rid if case != "missing_headers" else None,
                            "synthetic_response_request_id": original})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", choices=("https://localhost", "https://abdm.healthdoc.world"), default="https://localhost")
    parser.add_argument("--ca-cert", type=Path)
    args = parser.parse_args()
    results = probe(base_url=args.base_url, ca_cert=args.ca_cert)
    print(json.dumps({"nha_request_sent": False, "results": results}, indent=2))
    raise SystemExit(0 if all(row["passed"] for row in results) else 1)
