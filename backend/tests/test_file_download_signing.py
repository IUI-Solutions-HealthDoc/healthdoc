"""Offline signing tests: no storage, database or public endpoint is contacted."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.files import minio_client, service


def settings():
    return SimpleNamespace(
        environment="production",
        minio_endpoint="minio:9000",
        minio_public_endpoint="files.example.test",
        minio_region="us-east-1",
        minio_root_user="synthetic-access",
        minio_root_password="synthetic-secret",
    )


def test_download_signs_original_public_https_host_without_storage_io(monkeypatch):
    configured = settings()
    monkeypatch.setattr(minio_client, "get_settings", lambda: configured)
    client = minio_client.get_download_client()

    def forbidden(*args, **kwargs):
        raise AssertionError("Signing must not query the public storage host")

    monkeypatch.setattr(client, "_url_open", forbidden)
    url = client.presigned_get_object(
        "hd-files",
        "facility/orders/synthetic.pdf",
        expires=timedelta(seconds=300),
        request_date=datetime(2026, 1, 1, tzinfo=UTC),
    )
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.netloc == "files.example.test"
    assert parsed.path == "/hd-files/facility/orders/synthetic.pdf"
    query = parse_qs(parsed.query)
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert query["X-Amz-Expires"] == ["300"]
    assert "/us-east-1/s3/aws4_request" in query["X-Amz-Credential"][0]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert configured.minio_endpoint == "minio:9000", "internal upload endpoint is unchanged"


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "",
        "https://files.example.test",
        "files.example.test/path",
        "files.example.test?query",
        "files.example.test#fragment",
        "user:secret@files.example.test",
        "[broken",
        "files.example.test:bad",
    ],
)
def test_production_download_rejects_missing_or_invalid_endpoint(monkeypatch, endpoint):
    configured = settings()
    configured.minio_public_endpoint = endpoint
    monkeypatch.setattr(minio_client, "get_settings", lambda: configured)
    with pytest.raises(HTTPException) as error:
        minio_client.get_download_client()
    assert error.value.status_code == 503
    assert "secret@" not in error.value.detail


def test_local_development_retains_direct_storage_fallback(monkeypatch):
    configured = settings()
    configured.environment = "dev"
    configured.minio_public_endpoint = None
    direct = object()
    monkeypatch.setattr(minio_client, "get_settings", lambda: configured)
    monkeypatch.setattr(minio_client, "get_minio_client", lambda: direct)
    assert minio_client.get_download_client() is direct


async def test_download_service_uses_public_signer_after_authorization_and_logs_access(monkeypatch):
    record = SimpleNamespace(
        id=uuid4(), bucket="hd-files", object_key="synthetic.pdf", is_erased=False
    )
    calls, logs = [], []

    async def get_record(db, file_id, *, facility_id):
        calls.append(("authorized", file_id, facility_id))
        return record

    def presign(bucket, key, *, expires):
        calls.append(("signed", bucket, key, expires))
        return "https://files.example.test/synthetic.pdf"

    async def flush():
        pass

    monkeypatch.setattr(service, "get_file_record", get_record)
    monkeypatch.setattr(
        service, "get_download_client", lambda: SimpleNamespace(presigned_get_object=presign)
    )
    db = SimpleNamespace(add=logs.append, flush=flush)
    actor, facility = uuid4(), uuid4()
    url = await service.get_download_url(
        db, record.id, facility_id=facility, user_id=actor, ip_address=None
    )
    assert url.startswith("https://files.example.test/")
    assert calls[0] == ("authorized", record.id, facility)
    assert calls[1][0] == "signed" and calls[1][-1] == timedelta(seconds=300)
    assert (
        logs[0].file_id == record.id and logs[0].user_id == actor and logs[0].action == "download"
    )
    record.is_erased = True
    with pytest.raises(HTTPException) as error:
        await service.get_download_url(
            db, record.id, facility_id=facility, user_id=actor, ip_address=None
        )
    assert error.value.status_code == 410
    assert len(logs) == 1 and sum(call[0] == "signed" for call in calls) == 1
