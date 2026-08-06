"""MinIO client — thin async wrapper around the official sync SDK.

The minio package (v7) is sync-only. We wrap blocking calls in
run_in_executor so they don't block the event loop. One client instance
is created at startup and reused (thread-safe per the SDK docs).

Usage:
    from app.common.storage import get_storage
    storage = get_storage()
    url = await storage.presign_get(object_name, expires_seconds=3600)
"""
from __future__ import annotations

import asyncio
import datetime
import io
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from app.common.config import get_settings


class StorageClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=False,  # internal service — TLS terminated at ingress
        )
        self._bucket = settings.minio_bucket_files

    def _loop(self):
        return asyncio.get_event_loop()

    async def ensure_bucket(self) -> None:
        """Create bucket if it doesn't exist — called once at app startup."""
        def _sync():
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        await self._loop().run_in_executor(None, _sync)

    async def put_object(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload bytes under object_name in the files bucket."""
        def _sync():
            self._client.put_object(
                self._bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        await self._loop().run_in_executor(None, _sync)

    async def presign_get(
        self,
        object_name: str,
        expires_seconds: int = 3600,
    ) -> str:
        """Return a pre-signed GET URL valid for expires_seconds."""
        def _sync():
            return self._client.presigned_get_object(
                self._bucket,
                object_name,
                expires=datetime.timedelta(seconds=expires_seconds),
            )
        return await self._loop().run_in_executor(None, _sync)

    async def object_exists(self, object_name: str) -> bool:
        """Return True if the object exists (stat_object succeeds)."""
        def _sync():
            try:
                self._client.stat_object(self._bucket, object_name)
                return True
            except S3Error as e:
                if e.code == "NoSuchKey":
                    return False
                raise
        return await self._loop().run_in_executor(None, _sync)


@lru_cache
def get_storage() -> StorageClient:
    return StorageClient()
