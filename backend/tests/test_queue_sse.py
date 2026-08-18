"""Tests for the public queue display SSE stream (queue/router.py's
queue_display_stream).

Runs against a REAL server rather than an in-process ASGITransport, so the
stream is exercised over a real socket with real client disconnects.

These previously required a developer to have uvicorn already listening on
port 8000 and Redis resolvable as the host 'redis' — neither true in CI or on
a developer's machine — so both skipped every run. The live_server fixture
boots its own uvicorn on an ephemeral port and the Redis client comes from
settings, so they run everywhere.

The second test is the one that matters: it is what proved EnvelopeMiddleware
was leaking a Redis subscription per dropped client, and it is what stops that
regressing.
"""
import asyncio
import json

import httpx
import pytest
import redis.asyncio as redis_async

from app.common.redis import queue_channel


@pytest.fixture(scope="module")
def live_server():
    """A real uvicorn on an ephemeral port, for the length of this module.

    These used to require uvicorn already listening on port 8000 and Redis
    resolvable as the host 'redis'. Neither holds in CI or on a developer's
    machine, so both tests skipped every single run and the queue display
    stream — the screen in the waiting room — had no coverage at all.
    Booting our own server on an ephemeral port removes the precondition.
    """
    import threading
    import time as _time

    import uvicorn

    from app.main import app

    # ws="none": this module only speaks SSE over plain HTTP. Left on, uvicorn
    # imports its websockets protocol implementation, which pulls in
    # websockets.legacy and emits two third-party DeprecationWarnings we have no
    # way to fix. Not loading it is better than filtering the warning.
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", ws="none")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = _time.monotonic() + 30
    while not server.started:
        if _time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start within 30s")
        _time.sleep(0.05)

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _redis_client() -> redis_async.Redis:
    # From settings, not a hardcoded 'redis' host — that name only resolves
    # inside docker compose, so it could never work from a developer's machine.
    from app.common.config import get_settings

    return redis_async.from_url(get_settings().redis_url, decode_responses=True)


async def _first_line(response: httpx.Response) -> str:
    async for line in response.aiter_lines():
        return line
    raise AssertionError("stream ended with no lines")


@pytest.mark.asyncio
async def test_sse_stream_forwards_published_event(live_server):
    department_id = "22222222-2222-2222-2222-222222222222"
    path = f"/api/v1/queue/display/{department_id}/stream"

    r = _redis_client()
    try:
        async with httpx.AsyncClient(base_url=live_server, timeout=10) as ac:
            async with ac.stream("GET", path) as response:
                assert response.status_code == 200
                await asyncio.sleep(0.3)

                payload = {
                    "department_id": department_id,
                    "queue_id": "test-queue",
                    "doctor_name": "Dr. Test",
                    "room_number": "1",
                    "token_display": "TST-001",
                    "now_serving": "TST-001",
                }
                await r.publish(
                    queue_channel(department_id),
                    json.dumps({"event_type": "token_called", "payload": payload}),
                )

                line = await asyncio.wait_for(_first_line(response), timeout=5)
                assert line.startswith("data:")
                assert "token_called" in line
                assert "TST-001" in line
                assert "patient" not in line.lower()
                assert "uhid" not in line.lower()
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_sse_stream_unsubscribes_on_disconnect(live_server):
    department_id = "33333333-3333-3333-3333-333333333333"
    channel = queue_channel(department_id)
    path = f"/api/v1/queue/display/{department_id}/stream"

    r = _redis_client()
    try:
        async with httpx.AsyncClient(base_url=live_server, timeout=10) as ac:
            async with ac.stream("GET", path) as response:
                assert response.status_code == 200
                await asyncio.sleep(0.3)
                assert channel in await r.pubsub_channels()

        await asyncio.sleep(1.5)
        assert channel not in await r.pubsub_channels(), (
            "Redis subscription was not cleaned up after client disconnect. "
            "This is the leak that made EnvelopeMiddleware raw ASGI: a "
            "BaseHTTPMiddleware never forwards http.disconnect, so the SSE "
            "generator is never closed and subscribe()'s finally never runs."
        )
    finally:
        await r.aclose()
