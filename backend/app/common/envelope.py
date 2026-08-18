"""Response envelope middleware — B1-W1-06.

Every JSON API response is wrapped as:
  {"success": bool, "data": ..., "error": null | {"code", "message"}, "meta": {...}}
Handlers just return their payload; this middleware wraps it.
Docs/openapi/health endpoints pass through untouched.

WHY THIS IS RAW ASGI AND NOT BaseHTTPMiddleware
-----------------------------------------------
It used to subclass BaseHTTPMiddleware. That class runs the downstream app as a
task and bridges it with memory streams, and the bridge does not forward
`http.disconnect` to the endpoint. For ordinary request/response that is
invisible. For a streaming endpoint it is a resource leak:

    async with subscribe(channel) as pubsub:      # queue/router.py
        async for message in pubsub.listen():
            yield ...

When the client goes away, the endpoint never learns, the generator is never
closed, `subscribe()`'s finally never runs, and the Redis subscription stays
open for the life of the process. A waiting-room display that reconnects on
every network blip leaks one subscription per reconnect. Proven by
tests/test_queue_sse.py::test_sse_stream_unsubscribes_on_disconnect.

A raw ASGI middleware has no such bridge: `receive` and `send` are the real
ones, so disconnects reach the endpoint and streaming stays streaming.

The buffering decision is made from the `http.response.start` message, before
any body arrives — only `application/json` is collected and rewrapped.
`text/event-stream` and everything else is forwarded chunk by chunk.
"""
import json
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SKIP_PATHS = ("/docs", "/openapi.json", "/redoc")


class EnvelopeMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        request_id = headers.get("x-request-id", str(uuid.uuid4()))
        path = scope.get("path", "")
        skip_path = any(path.endswith(p) for p in SKIP_PATHS)

        # Set by handle_start, read by handle_body.
        state: dict = {"wrap": False, "start": None, "body": bytearray()}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id

                content_type = response_headers.get("content-type", "").split(";")[0]
                state["wrap"] = not skip_path and content_type == "application/json"

                if state["wrap"]:
                    # Hold the start message back: the body has to be rewrapped
                    # before content-length can be correct.
                    state["start"] = message
                    return
                await send(message)
                return

            if message["type"] == "http.response.body" and state["wrap"]:
                state["body"].extend(message.get("body", b""))
                if message.get("more_body", False):
                    return
                await self._send_envelope(send, state, request_id)
                return

            # Streaming responses (text/event-stream), file responses, anything
            # non-JSON: forwarded untouched, one chunk at a time.
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    async def _send_envelope(send: Send, state: dict, request_id: str) -> None:
        start = state["start"]
        body = bytes(state["body"])
        status = start["status"]

        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            # Not actually JSON despite the header — pass the bytes through
            # rather than corrupting them.
            await send(start)
            await send({"type": "http.response.body", "body": body})
            return

        if isinstance(payload, dict) and {"success", "data", "error"} <= payload.keys():
            envelope = payload  # already wrapped (e.g. exception handler)
        elif status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            envelope = {
                "success": False,
                "data": None,
                "error": {"code": status, "message": detail},
                "meta": {"request_id": request_id},
            }
        else:
            envelope = {
                "success": True,
                "data": payload,
                "error": None,
                "meta": {"request_id": request_id},
            }

        out = json.dumps(envelope, default=str).encode()
        headers = MutableHeaders(scope=start)
        headers["content-length"] = str(len(out))
        await send(start)
        await send({"type": "http.response.body", "body": out})
