"""Tests for the public queue display SSE stream (queue/router.py's
queue_display_stream).

Connects to the REAL running server (localhost:8000, same process this
runs alongside in the container) rather than using an in-process
ASGITransport -- ASGITransport + EnvelopeMiddleware (BaseHTTPMiddleware)
deadlocks on any streaming response: call_next() partially drains the
response's internal message pipe to inspect headers, then a second read
of that same pipe (for pass-through) has nothing left until real content
arrives, which for this endpoint depends on Redis, which depends on the
test publishing, which depends on the stream already being open. A real
running server doesn't have this problem -- confirmed manually with curl
before this test existed.
"""
import asyncio
import json

import httpx
import pytest
import redis.asyncio as redis_async

from app.common.redis import queue_channel


def _redis_client() -> redis_async.Redis:
    return redis_async.Redis(host="redis", port=6379, decode_responses=True)


async def _first_line(response: httpx.Response) -> str:
    async for line in response.aiter_lines():
        return line
    raise AssertionError("stream ended with no lines")


@pytest.mark.asyncio
async def test_sse_stream_forwards_published_event():
    department_id = "22222222-2222-2222-2222-222222222222"
    path = f"/api/v1/queue/display/{department_id}/stream"

    r = _redis_client()
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as ac:
            async with ac.stream("GET", path) as response:
                assert response.status_code == 200
                await asyncio.sleep(0.3)  # let the subscribe register first

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
async def test_sse_stream_unsubscribes_on_disconnect():
    department_id = "33333333-3333-3333-3333-333333333333"
    channel = queue_channel(department_id)
    path = f"/api/v1/queue/display/{department_id}/stream"

    r = _redis_client()
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as ac:
            async with ac.stream("GET", path) as response:
                assert response.status_code == 200
                await asyncio.sleep(0.3)
                assert channel in await r.pubsub_channels()

        # Exiting the outer `async with` closes the connection -- a real disconnect.
        await asyncio.sleep(1.5)
        assert channel not in await r.pubsub_channels(), (
            "Redis subscription was not cleaned up after client disconnect -- "
            "known blocker: EnvelopeMiddleware/BaseHTTPMiddleware incompatible "
            "with streaming responses, confirmed but not yet fixed."
        )
    finally:
        await r.aclose()
