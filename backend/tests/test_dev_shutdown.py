"""An open wall-display stream must not prevent a development worker restart."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml


def test_dev_worker_stops_with_an_open_sse_connection(tmp_path):
    import socket

    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "infra/docker-compose.yml").read_text())
    command = list(compose["services"]["backend"]["command"])
    # Exercise the same worker configuration used by WatchFiles, without the
    # parent watcher. Reload sends SIGTERM to this worker and waits for it.
    command.remove("--reload")
    command[command.index("--host") + 1] = "127.0.0.1"
    command[command.index("--port") + 1] = "0"
    with socket.socket() as listener, (tmp_path / "server.log").open("w+") as log:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        command.extend(["--fd", str(listener.fileno())])
        process = subprocess.Popen(
            [sys.executable, "-m", *command],
            cwd=root / "backend",
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert process.poll() is None, "development worker exited before startup"
                    assert time.monotonic() < deadline, "development worker did not start"
                    time.sleep(0.1)
                with client.stream(
                    "GET", "/api/v1/queue/display/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee/stream"
                ) as response:
                    assert response.status_code == 200
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        raise AssertionError(
                            "The dev worker still waits for SSE after eight seconds; "
                            "WatchFiles reload would leave every API unavailable."
                        ) from None
                    # Uvicorn re-raises the original signal after graceful
                    # shutdown. Both that exit and a normal exit are valid.
                    assert process.returncode in (0, -signal.SIGTERM)
                    log.seek(0)
                    assert "Application shutdown complete" in log.read()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
