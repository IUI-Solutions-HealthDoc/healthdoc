"""Receiver receipts must survive refusal without becoming a new PHI/token store."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.envelope import EnvelopeMiddleware
from app.common.security import decrypt_pii
from app.integrations.abdm import callback_evidence as evidence

PATH = "/api/v3/hip/token/on-generate-token"


@pytest.fixture
def receipt_app(db, monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", "dkWUFyQpoVWEpmm4NovS1ketf25uP0WKr6z/sNC1ADk=")
    from app.common.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(evidence, "SessionLocal", async_sessionmaker(db.bind, expire_on_commit=False))
    app = FastAPI()
    app.add_middleware(EnvelopeMiddleware)
    app.add_middleware(evidence.CallbackEvidenceMiddleware, enabled=True)
    yield app
    get_settings.cache_clear()


def decoded(row):
    return json.loads(decrypt_pii(row.evidence_encrypted, associated_data=evidence.aad(row.id)))


@pytest.mark.parametrize("status", [202, 400, 404, 422, 500])
async def test_real_http_outcome_is_durable_and_redacted(db, receipt_app, status, caplog):
    @receipt_app.post(PATH)
    async def receiver(request: Request):
        await request.json()
        if status >= 400:
            raise HTTPException(status, {"code": "missing_abdm_headers", "message": "private-message"})
        from fastapi import Response
        return Response(status_code=202)

    rid, original = str(uuid.uuid4()), str(uuid.uuid4())
    body = {"abhaAddress": "private-person@sbx", "linkToken": "secret-link-token",
            "response": {"requestId": original}, "private-field-name": "private-value"}
    async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
        result = await client.post(PATH, json=body, headers={
            "REQUEST-ID": rid, "Authorization": "Bearer private-auth", "Cookie": "private-cookie",
            "CF-Connecting-IP": "192.0.2.5", "X-Forwarded-For": "192.0.2.6, invalid-IP",
        })
    assert result.status_code == status
    row = (await db.execute(select(evidence.AbdmCallbackReceipt))).scalar_one()
    assert str(row.id) == result.headers["x-healthdoc-receipt-id"]
    assert row.status_code == status and row.completed_at
    assert str(row.request_id) == rid and str(row.response_request_id) == original
    snapshot = decoded(row)
    assert snapshot["headers"]["cf-connecting-ip"] == "192.0.2.5"
    assert snapshot["headers"]["x-forwarded-for"] == ["192.0.2.6", "invalid"]
    assert snapshot["source_ip_claims_trusted"] is False
    assert snapshot["request"]["body"]["response"]["requestId"] == original
    output = json.dumps(snapshot) + caplog.text
    for secret in ["private-person", "secret-link-token", "private-auth", "private-cookie",
                   "private-message", "private-field-name", "private-value"]:
        assert secret not in output and secret.encode() not in row.evidence_encrypted
    if status >= 400:
        assert "missing_abdm_headers" in output


async def test_receipt_survives_business_transaction_rollback(db, receipt_app):
    @receipt_app.post(PATH)
    async def receiver(request: Request):
        await request.json()
        async with evidence.SessionLocal() as session:
            async with session.begin():
                session.add(evidence.AbdmCallbackReceipt(
                    id=uuid.uuid4(), received_at=datetime.now(UTC), expires_at=datetime.now(UTC),
                    path="rollback-marker", method="POST", request_bytes=0, evidence_encrypted=b"test"))
                await session.flush()
                raise HTTPException(400, {"code": "invalid_timestamp"})
    async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
        assert (await client.post(PATH, json={})).status_code == 400
    rows = (await db.execute(select(evidence.AbdmCallbackReceipt))).scalars().all()
    assert len(rows) == 1 and rows[0].path == PATH and rows[0].status_code == 400


async def test_unhandled_exception_leaves_500_receipt_without_exception_text(db, receipt_app, caplog):
    @receipt_app.post(PATH)
    async def receiver(request: Request):
        await request.json()
        raise RuntimeError("secret-exception-value")
    async with AsyncClient(transport=ASGITransport(app=receipt_app, raise_app_exceptions=False), base_url="https://test") as client:
        assert (await client.post(PATH, json={})).status_code == 500
    row = (await db.execute(select(evidence.AbdmCallbackReceipt))).scalar_one()
    assert row.status_code == 500
    assert decoded(row)["handler_exception"] is True
    assert "secret-exception-value" not in caplog.text


@pytest.mark.parametrize("body,expected", [(b'{"linkToken":', "malformed_json"),
                                         (b"x" * (evidence.CAPTURE_BYTES + 1), "omitted_oversize_or_incomplete")])
async def test_invalid_and_oversized_bodies_are_not_retained(db, receipt_app, body, expected):
    @receipt_app.post(PATH)
    async def receiver(request: Request):
        await request.body()
        raise HTTPException(400)
    async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
        await client.post(PATH, content=body, headers={"Content-Type": "application/json"})
    row = (await db.execute(select(evidence.AbdmCallbackReceipt))).scalar_one()
    assert row.request_bytes == len(body)
    assert decoded(row)["request"]["capture"] == expected


async def test_storage_failure_cannot_change_response_or_leak_sql_parameters(receipt_app, monkeypatch, caplog):
    @receipt_app.post(PATH)
    async def receiver():
        raise HTTPException(400)
    sink = AsyncMock(side_effect=RuntimeError("secret-sql-parameters"))
    monkeypatch.setattr(evidence, "store_receipt", sink)
    before = evidence.SINK_FAILURES._value.get()
    async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
        assert (await client.post(PATH, json={})).status_code == 400
    assert sink.await_count == 2
    assert evidence.SINK_FAILURES._value.get() == before + 2
    assert "secret-sql-parameters" not in caplog.text


async def test_non_callback_routes_do_not_write_receipts(receipt_app, monkeypatch):
    sink = AsyncMock()
    monkeypatch.setattr(evidence, "store_receipt", sink)
    async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
        assert (await client.get("/api/v1/health")).status_code == 404
    sink.assert_not_awaited()


def test_safe_shape_keeps_validation_locations_not_input_or_credentials():
    result = evidence.safe_shape({"detail": [{"loc": ["body", "response", "requestId"],
                                             "type": "missing", "input": "private-input"}],
                                  "keyMaterial": {"nonce": "private-key", "keyValue": "private-key"}})
    output = json.dumps(result)
    assert "requestId" in output and "missing" in output
    assert "private-input" not in output and "private-key" not in output


async def test_expiry_deletes_only_expired_receipts(db, receipt_app):
    now = datetime.now(UTC)
    for delta in [-1, 1]:
        db.add(evidence.AbdmCallbackReceipt(id=uuid.uuid4(), received_at=now,
            expires_at=now + timedelta(days=delta), path=PATH, method="POST", request_bytes=0,
            evidence_encrypted=b"test"))
    await db.commit()
    assert await evidence.expire_receipts(db, now=now) == 1
    await db.commit()
    assert len((await db.execute(select(evidence.AbdmCallbackReceipt))).scalars().all()) == 1


def test_header_duplicates_and_injected_values_are_not_trusted():
    scope = {"headers": [(b"request-id", b"not-a-uuid"), (b"request-id", b"secret"),
                          (b"timestamp", b"bad-value"), (b"cf-connecting-ip", b"secret-value"),
                          (b"unknown-secret-header", b"private-header-value")]}
    assert evidence.safe_headers(scope) == {"request-id": "duplicate_header", "timestamp": "invalid",
                                            "cf-connecting-ip": "invalid"}


async def test_postgres_receipt_survives_rollback_in_an_independent_connection(receipt_app, monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL required; use make test-pg")
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(evidence, "SessionLocal", factory)
    marker = uuid.uuid4()

    @receipt_app.post(PATH)
    async def receiver(request: Request):
        await request.json()
        async with factory() as business:
            async with business.begin():
                business.add(evidence.AbdmCallbackReceipt(
                    id=marker, received_at=datetime.now(UTC), expires_at=datetime.now(UTC),
                    path="rollback-marker", method="POST", request_bytes=0, evidence_encrypted=b"test"))
                await business.flush()
                raise HTTPException(400, {"code": "invalid_timestamp"})

    try:
        async with AsyncClient(transport=ASGITransport(app=receipt_app), base_url="https://test") as client:
            response = await client.post(PATH, json={"linkToken": "synthetic-secret"})
        ident = uuid.UUID(response.headers["x-healthdoc-receipt-id"])
        async with factory() as verification:
            row = await verification.get(evidence.AbdmCallbackReceipt, ident)
            assert row.status_code == 400 and row.completed_at
            assert await verification.get(evidence.AbdmCallbackReceipt, marker) is None
            assert "invalid_timestamp" in json.dumps(decoded(row))
            assert "synthetic-secret" not in json.dumps(decoded(row))
            await verification.delete(row)  # Only this test's synthetic receipt.
            await verification.commit()
    finally:
        await engine.dispose()
