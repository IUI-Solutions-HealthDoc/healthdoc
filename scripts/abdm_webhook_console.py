#!/usr/bin/env python3
"""Read-only loopback view of the running HealthDoc container's redacted receipts.

No gateway calls, credentials, raw clinical bodies, database writes or delivery
controls. Docker access is the operator boundary; do not expose this port through
nginx, a tunnel or a LAN bind. Browser API reads require a same-origin custom header.
"""

import argparse
import json
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ASSETS = Path(__file__).with_name("abdm_webhook_console")
PRIVATE_KEYS = {"asgi_client_ip", "cf-connecting-ip", "x-forwarded-for"}


def shareable(value):
    """The container already redacts payloads; omit IP metadata from this view too."""
    if isinstance(value, dict):
        return {k: shareable(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [shareable(v) for v in value]
    return value


def read_container(container, kind, identifier=None):
    command = ["docker", "exec", container, "python", "-m"]
    if kind == "status":
        command += ["scripts.abdm_operational_status"]
    else:
        command += ["scripts.abdm_callback_receipts", "--limit", "50"]
        if identifier:
            # Parsing happens before command construction; no shell is involved.
            identifier = str(uuid.UUID(identifier))
            command += ["--id", identifier, "--details"] if kind == "receipt" else ["--request-id", identifier]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError("Receipt reader failed. Check Docker/backend availability in Terminal.")
    try:
        return shareable(json.loads(result.stdout))
    except json.JSONDecodeError:
        raise RuntimeError("Backend reader returned an invalid response") from None


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, container):
        self.container = container
        self.reader_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), ConsoleHandler)


class ConsoleHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # No request URLs, identifiers or bodies in host logs.

    def send_content(self, code, content, content_type="application/json"):
        encoded = content if isinstance(content, bytes) else json.dumps(content).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(encoded)

    def allowed(self, *, api):
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return not api or self.headers.get("X-HealthDoc-Operator-View") == "1"

    def do_GET(self):
        parsed = urlsplit(self.path)
        api = parsed.path.startswith("/api/")
        if not self.allowed(api=api):
            self.send_content(403, {"error": "Local operator view only; use its browser page or documented Postman header."})
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if parsed.path in assets:
            filename, content_type = assets[parsed.path]
            self.send_content(200, (ASSETS / filename).read_bytes(), content_type)
            return
        try:
            query = parse_qs(parsed.query, strict_parsing=True)
            if parsed.path == "/api/receipts":
                if set(query) - {"request_id"} or any(len(v) != 1 for v in query.values()):
                    raise ValueError
                kind, identifier = "receipts", query.get("request_id", [None])[0]
            elif parsed.path == "/api/receipt":
                if set(query) != {"id"} or len(query["id"]) != 1:
                    raise ValueError
                kind, identifier = "receipt", query["id"][0]
            elif parsed.path == "/api/status" and not query:
                kind, identifier = "status", None
            else:
                self.send_content(404, {"error": "Unknown read-only route"})
                return
            if identifier:
                uuid.UUID(identifier)
            with self.server.reader_lock:
                value = read_container(self.server.container, kind, identifier)
            self.send_content(200, value)
        except ValueError:
            self.send_content(400, {"error": "Use a valid UUID and the documented query field."})
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            self.send_content(503, {"error": "Cannot read the running backend. Check Docker/backend and retry; this is not an empty result."})

    def do_POST(self):
        self.send_content(405, {"error": "Read-only console; NHA callbacks belong at https://abdm.healthdoc.world/api/v3/..."})

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_POST


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--container", default="healthdoc-backend-1")
    options = parser.parse_args()
    server = ConsoleServer(options.port, options.container)
    print(f"HealthDoc webhook console: http://127.0.0.1:{server.server_address[1]}", flush=True)
    print("Read-only redacted view. Ctrl-C stops the console, not HealthDoc or its webhook.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
