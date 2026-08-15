"""
Tests for the files API service layer (B7-W6-01).

Repo path: backend/tests/files/test_files_api.py

Real Postgres AND real MinIO -- upload/download-url round-trips a real
object through the real SDK, not a mock, since the point of this ticket
is exactly "does the presigned URL actually work". Reuses conftest.py's
proven engine/facility_id/user_id fixtures (same real facilities/users
inserts already exercised by test_0019_files_db.py).

MINIO_ENDPOINT must be host-reachable (localhost:9000), not the
docker-internal `minio:9000` from .env -- see app/files/minio_client.py's
docstring. Set via the same environment-override convention as
TEST_DATABASE_URL.

TestFilesRouterHTTP goes through the REAL router (httpx.AsyncClient +
ASGITransport against a minimal app, same technique as tests/consent/
test_crud_api.py's dependency-order regression test) rather than calling
service functions directly, the way every other class here does. Calling
service.upload_file()/get_file_record()/get_download_url() directly
proves the service layer is correct but says nothing about require_roles,
CurrentDbUser, multipart Form(...) parsing, or the router's own call
order (get_file_record() then record_view_access(), separately) --
those only exist at the FastAPI routing layer, so this is the one place
that actually exercises the API surface the ticket asks for.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.deps import AuthUser, get_current_user
from app.common.db import get_db
from app.files import service
from app.files.router import router as files_router

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100
_HTML_DISGUISED_AS_JPG = b"<html><script>alert(document.cookie)</script></html>"


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _upload_file(data: bytes, filename: str = "test.jpg") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


async def _audit_row_for(engine: AsyncEngine, *, resource_id: uuid.UUID):
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT action, resource_type, new_value FROM audit_logs "
                "WHERE resource_type = 'files' AND resource_id = :rid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"rid": resource_id},
        )
        return result.one_or_none()


async def _access_log_rows(engine: AsyncEngine, *, file_id: uuid.UUID):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT action FROM file_access_log WHERE file_id = :fid ORDER BY accessed_at"),
            {"fid": file_id},
        )
        return [row.action for row in result]


class TestSniffContentType:
    def test_recognises_jpeg(self):
        assert service.sniff_content_type(_JPEG_BYTES) == "image/jpeg"

    def test_recognises_png(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert service.sniff_content_type(data) == "image/png"

    def test_recognises_pdf(self):
        data = b"%PDF-1.4\n" + b"\x00" * 100
        assert service.sniff_content_type(data) == "application/pdf"

    def test_recognises_dicom(self):
        data = b"\x00" * 128 + b"DICM" + b"\x00" * 100
        assert service.sniff_content_type(data) == "application/dicom"

    def test_rejects_html(self):
        assert service.sniff_content_type(_HTML_DISGUISED_AS_JPG) is None

    def test_rejects_empty(self):
        assert service.sniff_content_type(b"") is None


class TestUploadFile:
    pytestmark = pytest.mark.asyncio
    async def test_valid_upload_creates_record_logs_and_lands_in_minio(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db,
                upload=_upload_file(_JPEG_BYTES),
                facility_id=facility_id,
                uploaded_by=user_id,
                owner_module="patients",
                patient_id=None,
                sensitivity="normal",
                ip_address="10.0.0.1",
            )
            await db.commit()

        assert record.content_type == "image/jpeg"
        assert record.size_bytes == len(_JPEG_BYTES)
        assert record.sha256 == hashlib.sha256(_JPEG_BYTES).hexdigest()
        assert record.scan_status == "skipped"

        # audit_logs row (the mutation itself)
        audit_row = await _audit_row_for(engine, resource_id=record.id)
        assert audit_row is not None
        assert audit_row.action == "create"

        # file_access_log row (the ticket's own "+ access log")
        assert await _access_log_rows(engine, file_id=record.id) == ["upload"]

        # Proves the object is REALLY in MinIO, not just a DB row claiming so.
        from app.files.minio_client import get_minio_client
        stat = await asyncio.to_thread(get_minio_client().stat_object, record.bucket, record.object_key)
        assert stat.size == len(_JPEG_BYTES)

    async def test_rejects_content_that_fails_the_magic_byte_sniff(
        self, session_factory, facility_id, user_id
    ):
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.upload_file(
                    db,
                    upload=_upload_file(_HTML_DISGUISED_AS_JPG, filename="totally_a_photo.jpg"),
                    facility_id=facility_id, uploaded_by=user_id, owner_module=None,
                    patient_id=None, sensitivity="normal", ip_address=None,
                )
        assert exc_info.value.status_code == 422

    async def test_rejects_empty_file(self, session_factory, facility_id, user_id):
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.upload_file(
                    db, upload=_upload_file(b""), facility_id=facility_id, uploaded_by=user_id,
                    owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
                )
        assert exc_info.value.status_code == 422

    async def test_rejects_oversized_file(self, monkeypatch, session_factory, facility_id, user_id):
        monkeypatch.setattr(service, "MAX_FILE_SIZE_BYTES", 10)
        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.upload_file(
                    db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                    owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
                )
        assert exc_info.value.status_code == 413


class TestGetFileRecord:
    pytestmark = pytest.mark.asyncio
    async def test_facility_scoping_blocks_cross_facility_access(
        self, session_factory, facility_id, second_facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
            )
            await db.commit()

        async with session_factory() as db:
            found = await service.get_file_record(db, record.id, facility_id=facility_id)
        assert found.id == record.id

        async with session_factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await service.get_file_record(db, record.id, facility_id=second_facility_id)
        assert exc_info.value.status_code == 404


class TestGetDownloadUrl:
    pytestmark = pytest.mark.asyncio
    async def test_presigned_url_actually_serves_the_uploaded_bytes(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                owner_module=None, patient_id=None, sensitivity="normal", ip_address="10.0.0.2",
            )
            await db.commit()

        async with session_factory() as db:
            url = await service.get_download_url(
                db, record.id, facility_id=facility_id, user_id=user_id, ip_address="10.0.0.2",
            )
            await db.commit()

        assert await _access_log_rows(engine, file_id=record.id) == ["upload", "download"]

        # The actual proof: fetch the presigned URL for real and check bytes match.
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        assert response.status_code == 200
        assert response.content == _JPEG_BYTES


async def _keycloak_sub_for(engine: AsyncEngine, user_id: uuid.UUID) -> str:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT keycloak_sub FROM users WHERE id = :id"), {"id": user_id}
            )
        ).scalar_one()


def _client_for(sub: str, roles: list[str], session_factory) -> httpx.AsyncClient:
    """The router and get_current_db_user both depend on app.common.db's
    get_db, which owns its own module-level engine bound to
    settings.database_url (the real dev DB) -- created once, at import
    time, under whichever event loop happened to exist then. Left
    un-overridden, requests either resolve against the wrong database
    (get_current_db_user's "actor_not_provisioned" 403 for a user that
    only exists in healthdoc_test) or crash with asyncpg's "Future
    attached to a different loop" once pytest-asyncio hands this test a
    fresh loop. Overriding get_db with the test's own session_factory
    (bound to the `engine` fixture, on this test's loop) is required, not
    optional, for any test here that expects an actual 2xx/4xx from
    DB-backed logic rather than that mismatch.
    """
    async def _override_get_db():
        # Mirrors app.common.db.get_db's own commit-on-success/rollback-on-
        # error exactly -- a bare `yield session` here leaves every write
        # the handler makes (file row, access_log row) uncommitted, so a
        # second connection (the `engine` fixture) checking afterwards
        # sees nothing.
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(files_router)
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=sub, username="tester", roles=roles
    )
    app.dependency_overrides[get_db] = _override_get_db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestFilesRouterHTTP:
    """See module docstring for why this class alone goes through real
    HTTP requests instead of calling service functions directly."""

    pytestmark = pytest.mark.asyncio

    async def test_upload_endpoint_creates_a_file_and_logs(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        sub = await _keycloak_sub_for(engine, user_id)
        async with _client_for(sub, ["doctor"], session_factory) as client:
            response = await client.post(
                "/files/upload",
                files={"upload": ("test.jpg", _JPEG_BYTES, "image/jpeg")},
                data={"owner_module": "patients", "sensitivity": "normal"},
            )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["content_type"] == "image/jpeg"
        assert body["sha256"] == hashlib.sha256(_JPEG_BYTES).hexdigest()
        # §7: never expose internal object keys.
        assert "bucket" not in body
        assert "object_key" not in body

        file_id = uuid.UUID(body["id"])
        assert await _access_log_rows(engine, file_id=file_id) == ["upload"]
        audit_row = await _audit_row_for(engine, resource_id=file_id)
        assert audit_row is not None

    async def test_upload_endpoint_rejects_role_outside_allowlist(
        self, session_factory, engine: AsyncEngine, user_id
    ):
        sub = await _keycloak_sub_for(engine, user_id)
        async with _client_for(sub, ["patient"], session_factory) as client:  # not in _FILE_ROLES
            response = await client.post(
                "/files/upload", files={"upload": ("test.jpg", _JPEG_BYTES, "image/jpeg")},
            )
        assert response.status_code == 403

    async def test_upload_endpoint_bad_patient_id_is_404_not_500(
        self, session_factory, engine: AsyncEngine, user_id
    ):
        sub = await _keycloak_sub_for(engine, user_id)
        async with _client_for(sub, ["doctor"], session_factory) as client:
            response = await client.post(
                "/files/upload",
                files={"upload": ("test.jpg", _JPEG_BYTES, "image/jpeg")},
                data={"patient_id": str(uuid.uuid4())},  # doesn't exist
            )
        assert response.status_code == 404

    async def test_get_file_endpoint_returns_metadata_and_logs_view(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
            )
            await db.commit()

        sub = await _keycloak_sub_for(engine, user_id)
        async with _client_for(sub, ["doctor"], session_factory) as client:
            response = await client.get(f"/files/{record.id}")

        assert response.status_code == 200
        assert response.json()["id"] == str(record.id)
        # upload logged the row at seed time above; this GET must add a
        # second, "view" row -- proving get_file()'s own record_view_access()
        # call actually ran, not just service.get_file_record().
        assert await _access_log_rows(engine, file_id=record.id) == ["upload", "view"]

    async def test_get_file_endpoint_cross_facility_404s_without_logging(
        self, session_factory, engine: AsyncEngine, facility_id, second_facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
            )
            await db.commit()

        other_user_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, keycloak_sub, username, full_name, facility_id) "
                    "VALUES (:id, :sub, :sub, 'Other Facility User', :fid)"
                ),
                {"id": other_user_id, "sub": f"other-{other_user_id}", "fid": second_facility_id},
            )
        sub = await _keycloak_sub_for(engine, other_user_id)

        async with _client_for(sub, ["doctor"], session_factory) as client:
            response = await client.get(f"/files/{record.id}")

        assert response.status_code == 404
        # get_file_record() raised before record_view_access() could run.
        assert await _access_log_rows(engine, file_id=record.id) == ["upload"]

    async def test_download_url_endpoint_returns_a_working_url(
        self, session_factory, engine: AsyncEngine, facility_id, user_id
    ):
        async with session_factory() as db:
            record = await service.upload_file(
                db, upload=_upload_file(_JPEG_BYTES), facility_id=facility_id, uploaded_by=user_id,
                owner_module=None, patient_id=None, sensitivity="normal", ip_address=None,
            )
            await db.commit()

        sub = await _keycloak_sub_for(engine, user_id)
        async with _client_for(sub, ["doctor"], session_factory) as client:
            response = await client.get(f"/files/{record.id}/download-url")

        assert response.status_code == 200
        body = response.json()
        assert body["expires_in_seconds"] == service.PRESIGNED_URL_EXPIRY_SECONDS

        async with httpx.AsyncClient() as raw_client:
            fetched = await raw_client.get(body["url"])
        assert fetched.status_code == 200
        assert fetched.content == _JPEG_BYTES

        assert await _access_log_rows(engine, file_id=record.id) == ["upload", "download"]
