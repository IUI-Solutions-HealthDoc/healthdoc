"""Durable, privacy-minimised receipts for official callback HTTP traffic.

These are RECEIVER diagnostics, never proof of NHA origin or certification.
Raw tokens, patient identifiers, clinical content and arbitrary header values
are never retained. Even the redacted snapshot (including IP claims) is encrypted.
The receipt uses a separate transaction so a rejected callback cannot erase it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from prometheus_client import Counter
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, delete, update
from sqlalchemy.dialects.postgresql import UUID
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.db import Base, SessionLocal
from app.common.security import encrypt_pii

log = logging.getLogger("healthdoc.abdm.callback_evidence")
SINK_FAILURES = Counter("abdm_callback_evidence_failures_total", "Callback receipt storage failures")
CAPTURE_BYTES = 16 * 1024
RETENTION = timedelta(days=7)  # Operational debugging, NOT statutory audit retention.
SAFE_CODES = frozenset({
    "missing_abdm_headers", "invalid_request_id", "invalid_timestamp", "unknown_service",
    "invalid_cm_id", "stale_callback", "callback_replay_store_unavailable",
    "abdm_callbacks_not_configured", "link_not_found", "link_token_mismatch",
    "abdm_hfr_not_configured", "abdm_hfr_not_seeded", "json_body_too_large",
    "invalid_control_character", "unauthorised", "link_expired", "link_replay_conflict",
})
# Unknown field NAMES can also contain identifiers; do not preserve them blindly.
SAFE_KEYS = frozenset("""
    abhaAddress abhaNumber linkToken response requestId error code message entity
    transactionId timestamp notification hiRequest keyMaterial entries consent
    consentId consentRequestId consentDetail acknowledgement status patient id
    name gender yearOfBirth verifiedIdentifiers unverifiedIdentifiers type value
    referenceNumber display careContexts hiType count confirmation linkRefNumber
    token purpose permission dateRange from to dataEraseAt frequency accessMode
    hip hiu requester identifier system dataPushUrl dhPublicKey cryptoAlg curve
    expiry parameters keyValue nonce content media checksum careContextReference
    pageNumber pageCount careContextReferenceNumber contentType data sessionStatus
    transferStatus responses detail loc msg input ctx url success meta request_id
    consentArtefacts consentStatus healthInformation patientReferenceNumber
""".split())
SAFE_STATUSES = frozenset({
    "GRANTED", "DENIED", "REVOKED", "EXPIRED", "REQUESTED", "ACKNOWLEDGED",
    "OK", "ERRORED", "RECEIVED", "TRANSFERRED", "FAILED",
})


class AbdmCallbackReceipt(Base):
    __tablename__ = "abdm_callback_receipts"
    id = Column(UUID(as_uuid=True), primary_key=True)
    received_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    request_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    response_request_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    path = Column(String(250), nullable=False)
    method = Column(String(50), nullable=False)
    status_code = Column(Integer, nullable=True)
    request_bytes = Column(Integer, nullable=False, default=0)
    evidence_encrypted = Column(LargeBinary, nullable=False)


def aad(ident: uuid.UUID) -> bytes:
    return f"abdm-callback-receipt:{ident}".encode()


def valid_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def ip_claim(value: str) -> str:
    try:
        # Zone identifiers are neither required nor safe caller attribution.
        if "%" in value:
            return "invalid"
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return "invalid"


def safe_headers(scope: Scope) -> dict:
    headers = {}
    for name, value in scope.get("headers", []):
        key = name.decode("latin-1").lower()
        if key in {"request-id", "timestamp", "x-hip-id", "x-hiu-id", "x-cm-id",
                   "authorization", "content-type", "cf-connecting-ip", "x-forwarded-for"}:
            headers.setdefault(key, []).append(value.decode("latin-1"))
    output = {}
    for key, values in headers.items():
        if len(values) != 1:
            output[key] = "duplicate_header"
            continue
        value = values[0]
        if key == "request-id":
            output[key] = str(valid_uuid(value) or "invalid")
        elif key == "cf-connecting-ip":
            output[key] = ip_claim(value)
        elif key == "x-forwarded-for":
            output[key] = [ip_claim(v) for v in value[:512].split(",")[:8]]
        elif key == "timestamp":
            try:
                output[key] = datetime.fromisoformat(value[:50].replace("Z", "+00:00")).isoformat()
            except ValueError:
                output[key] = "invalid"
        elif key == "content-type":
            output[key] = "application/json" if value.split(";", 1)[0] == "application/json" else "other"
        else:
            output[key] = "present_redacted"
    return output


def safe_shape(value: object, *, key: str = "", depth: int = 0, budget=None) -> object:
    budget = [256] if budget is None else budget
    budget[0] -= 1
    if depth >= 8 or budget[0] < 0:
        return "omitted_limit"
    if isinstance(value, dict):
        result = {}
        omitted = 0
        for name, child in list(value.items())[:40]:
            if name in SAFE_KEYS:
                result[name] = safe_shape(child, key=name, depth=depth + 1, budget=budget)
            else:
                omitted += 1
        if omitted or len(value) > 40:
            overflow = len(value) - 40 if len(value) > 40 else 0
            result["_omitted_fields"] = omitted + overflow
        return result
    if isinstance(value, list):
        return {"_array_count": len(value), "_sample": [
            safe_shape(v, key=key, depth=depth + 1, budget=budget) for v in value[:5]
        ]}
    if value is None:
        return None
    if key in {"requestId", "request_id", "transactionId"} and valid_uuid(value):
        return str(valid_uuid(value))
    if key == "code" and isinstance(value, str):
        if value in SAFE_CODES or (len(value) == 9 and value.startswith("ABDM-") and value[5:].isdigit()):
            return value
    if key == "status" and isinstance(value, str) and value in SAFE_STATUSES:
        return value
    if key == "loc" and isinstance(value, str) and value in SAFE_KEYS | {"body", "header", "query"}:
        return value
    if key == "type" and isinstance(value, str) and value in {
        "missing", "string_type", "uuid_parsing", "json_invalid", "model_attributes_type",
        "dict_type", "list_type", "int_parsing", "datetime_parsing",
    }:
        return value
    return {"_redacted_type": type(value).__name__}


def body_snapshot(body: bytes, *, total: int, complete: bool) -> tuple[dict, uuid.UUID | None]:
    if total > CAPTURE_BYTES or not complete:
        return {"capture": "omitted_oversize_or_incomplete", "bytes": total}, None
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {"capture": "empty" if not body else "malformed_json", "bytes": total}, None
    response = value.get("response") if isinstance(value, dict) else None
    correlation = valid_uuid(response.get("requestId")) if isinstance(response, dict) else None
    return {"capture": "redacted_json", "body": safe_shape(value)}, correlation


async def store_receipt(ident: uuid.UUID, values: dict, *, initial: bool) -> None:
    """Independent commit; never mask the real callback outcome on sink failure."""
    async with asyncio.timeout(2):
        async with SessionLocal() as db:
            if initial and await db.get(AbdmCallbackReceipt, ident) is None:
                db.add(AbdmCallbackReceipt(id=ident, **values))
            else:
                await db.execute(update(AbdmCallbackReceipt).where(
                    AbdmCallbackReceipt.id == ident
                ).values(**values))
            await db.commit()


async def expire_receipts(db, *, now: datetime) -> int:
    result = await db.execute(delete(AbdmCallbackReceipt).where(AbdmCallbackReceipt.expires_at <= now))
    return result.rowcount


class CallbackEvidenceMiddleware:
    def __init__(self, app: ASGIApp, *, enabled: bool = False):
        self.app, self.enabled = app, enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http" or not scope.get("path", "").startswith("/api/v3/"):
            await self.app(scope, receive, send)
            return
        from app.integrations.abdm.external_router import router

        known_paths = {route.path for route in router.routes}
        path = scope["path"] if scope["path"] in known_paths else "/api/v3/<unmatched>"
        method = scope.get("method", "")
        method = method if method in {"POST", "GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER"
        ident, now = uuid.uuid4(), datetime.now(UTC)
        headers = safe_headers(scope)
        snapshot = {"headers": headers, "source_ip_claims_trusted": False,
                    "asgi_client_ip": ip_claim((scope.get("client") or ("",))[0])}
        values = dict(received_at=now, expires_at=now + RETENTION, path=path, method=method,
                      request_id=valid_uuid(headers.get("request-id")), request_bytes=0)

        async def persist(data: dict, *, initial: bool) -> bool:
            try:
                encrypted = encrypt_pii(json.dumps(snapshot), associated_data=aad(ident))
                await store_receipt(ident, {**data, "evidence_encrypted": encrypted}, initial=initial)
                return True
            except Exception:
                SINK_FAILURES.inc()
                # Exception strings / SQL parameters can contain snapshots; never log them.
                log.error("ABDM callback receipt storage failed receipt_id=%s", ident)
                return False

        stored = await persist(values, initial=True)
        request_body, response_body = bytearray(), bytearray()
        request_total = response_total = 0
        request_complete = response_complete = False
        status = None

        async def observed_receive() -> Message:
            nonlocal request_total, request_complete
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                request_total += len(chunk)
                request_body.extend(chunk[:max(0, CAPTURE_BYTES - len(request_body))])
                request_complete = not message.get("more_body", False)
            return message

        async def observed_send(message: Message) -> None:
            nonlocal status, response_total, response_complete
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": list(message.get("headers", [])) + [
                    (b"x-healthdoc-receipt-id", str(ident).encode())
                ]}
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                response_total += len(chunk)
                response_body.extend(chunk[:max(0, CAPTURE_BYTES - len(response_body))])
                response_complete = not message.get("more_body", False)
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        except Exception:
            snapshot["handler_exception"] = True
            if status is None:
                status = 500
            raise
        finally:
            snapshot["request"], correlation = body_snapshot(
                bytes(request_body), total=request_total, complete=request_complete)
            snapshot["response"], _ = body_snapshot(
                bytes(response_body), total=response_total, complete=response_complete)
            snapshot["response_complete"] = response_complete
            finished = dict(completed_at=datetime.now(UTC), status_code=status,
                            response_request_id=correlation, request_bytes=request_total)
            await persist(finished if stored else {**values, **finished}, initial=not stored)
            # Searchable stderr fallback has no body, IP, arbitrary headers or exception text.
            log.log(logging.WARNING if status is None or status >= 400 else logging.INFO,
                    "ABDM callback receipt_id=%s request_id=%s path=%s status=%s",
                    ident, values["request_id"], path, status)
