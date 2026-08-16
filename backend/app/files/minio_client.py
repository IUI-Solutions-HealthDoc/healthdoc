"""MinIO client for the files module.

Repo path: backend/app/files/minio_client.py

Kept inside app/files/ rather than app/common/ -- this module's own
client, not shared infra another module reaches into. Same singleton
shape as app/common/mongo.py / redis.py otherwise.

The minio SDK is synchronous (blocking socket I/O) -- every call through
this module must go through asyncio.to_thread() at the call site (see
service.py), never awaited directly, or it blocks the event loop for
every other request.

secure=False: this repo's docker-compose MinIO (and every local/dev
deployment described in .env.example) is plain HTTP behind the internal
network; TLS termination for the public path happens at the nginx edge
per B1-W1-03, not at MinIO itself. Hardcoded rather than a new Settings
field -- app/common/config.py isn't this module's file to extend; flag to
whoever owns it if production ever needs MinIO itself to speak TLS.
"""
from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from app.common.config import get_settings

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=False,
        )
    return _client


def ensure_bucket(bucket_name: str) -> None:
    """Idempotent, blocking -- call via asyncio.to_thread(). Local/dev
    MinIO has no separate provisioning step today, so callers create
    their bucket lazily on first real use rather than 404ing forever.

    bucket_exists() then make_bucket() is a check-then-act race: two
    concurrent first-uploads can both see "doesn't exist" and both call
    make_bucket(). Only matters once, ever, per bucket -- but unhandled,
    the loser's request would 500. BucketAlreadyOwnedByYou means someone
    else (with the same credentials) won the race a moment earlier,
    which is exactly the benign case this exists to survive; anything
    else is a real error and still raises.
    """
    client = get_minio_client()
    if client.bucket_exists(bucket_name):
        return
    try:
        client.make_bucket(bucket_name)
    except S3Error as exc:
        if exc.code != "BucketAlreadyOwnedByYou":
            raise
