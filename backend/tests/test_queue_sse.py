"""Tests for the public queue display SSE stream (queue/router.py's
queue_display_stream).

Connects to the REAL running server, not an in-process ASGITransport --
ASGITransport + EnvelopeMiddleware deadlocks on any streaming response
(confirmed via manual curl testing).

Skipped when a live server/Redis aren't reachable (e.g. CI) -- same
pattern as test_queue_counters_concurrency.py's _real_database_is_ready().
"""
import asyncio
import json
import socket

import httpx
import pytest
import redis.asyncio as redis_async

from app.common.redis import queue_channel


def _server_and_redis_are_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 8000), timeout=1):
            pass
        with socket.create_connection(("redis", 6379), timeout=1):
            pass
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _server_and_redis_are_reachable(),
    reason="Needs a live uvicorn server on localhost:8000 and Redis on 'redis' -- local dev only.",
)


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

        await asyncio.sleep(1.5)
        assert channel not in await r.pubsub_channels(), (
            "Redis subscription was not cleaned up after client disconnect -- "
            "known blocker: EnvelopeMiddleware/BaseHTTPMiddleware."
        )
    finally:
        await r.aclose()
