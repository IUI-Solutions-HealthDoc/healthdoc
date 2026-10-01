"""Local diagnostics must not become a public receipt or command execution API."""

import importlib.util
import json
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("console", Path(__file__).resolve().parents[1] / "abdm_webhook_console.py")
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)


class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = console.ConsoleServer(0, "synthetic-backend")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path="/api/receipts", *, headers=None, method="GET"):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        status, response_headers, body = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, body

    def test_browser_page_works_without_returning_receipts(self):
        with patch.object(console, "read_container") as reader:
            status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"HealthDoc", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        reader.assert_not_called()

    def test_rebinding_cross_origin_and_simple_requests_cannot_read(self):
        for headers in [{}, {"Host": "attacker.test"}, {"Origin": "https://attacker.test", "X-HealthDoc-Operator-View": "1"}, {"Sec-Fetch-Site": "cross-site", "X-HealthDoc-Operator-View": "1"}]:
            with self.subTest(headers=headers), patch.object(console, "read_container") as reader:
                self.assertEqual(self.request(headers=headers)[0], 403)
                reader.assert_not_called()

    def test_expected_operator_header_can_read_and_no_cors_is_granted(self):
        with patch.object(console, "read_container", return_value=[]) as reader:
            status, headers, body = self.request(headers={"X-HealthDoc-Operator-View": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        reader.assert_called_once_with("synthetic-backend", "receipts", None)

    def test_unknown_or_invalid_params_never_reach_docker(self):
        for path in ["/api/receipt", "/api/receipt?id=not-a-uuid", "/api/receipts?request_id=bad", "/api/receipts?command=whoami", "/api/receipt?id=x&id=y"]:
            with self.subTest(path=path), patch.object(console, "read_container") as reader:
                self.assertEqual(self.request(path, headers={"X-HealthDoc-Operator-View": "1"})[0], 400)
                reader.assert_not_called()

    def test_read_failure_is_not_empty_success_and_never_echoes_exception(self):
        with patch.object(console, "read_container", side_effect=RuntimeError("synthetic-private-token")):
            status, _, body = self.request(headers={"X-HealthDoc-Operator-View": "1"})
        self.assertEqual(status, 503)
        self.assertNotIn(b"synthetic-private-token", body)

    def test_writes_and_preflight_are_refused(self):
        for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]:
            with self.subTest(method=method), patch.object(console, "read_container") as reader:
                self.assertEqual(self.request(method=method)[0], 405)
                reader.assert_not_called()

    def test_invalid_backend_json_is_service_failure_not_bad_operator_input(self):
        result = type("Result", (), {"returncode": 0, "stdout": "synthetic-private-error"})()
        with patch.object(console.subprocess, "run", return_value=result):
            status, _, body = self.request(headers={"X-HealthDoc-Operator-View": "1"})
        self.assertEqual(status, 503)
        self.assertNotIn(b"synthetic-private-error", body)

    def test_docker_reader_keeps_uuid_separate_from_command_and_removes_ip_claims(self):
        ident = "00000000-0000-4000-8000-000000000001"
        result = type("Result", (), {"returncode": 0, "stdout": json.dumps([{"id": ident, "redacted_evidence": {"headers": {"cf-connecting-ip": "192.0.2.1", "authorization": "present_redacted"}, "asgi_client_ip": "192.0.2.2"}}])})()
        with patch.object(console.subprocess, "run", return_value=result) as run:
            data = console.read_container("synthetic-backend", "receipt", ident)
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], ["--id", ident, "--details"])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(data[0]["redacted_evidence"], {"headers": {"authorization": "present_redacted"}})


if __name__ == "__main__":
    unittest.main()
