"""MinIO client for the files module.

Repo path: backend/app/files/minio_client.py

Kept inside app/files/ rather than app/common/ -- this module's own
client, not shared infra another module reaches into. Same singleton
shape as app/common/mongo.py / redis.py otherwise.

The minio SDK is synchronous (blocking socket I/O) -- every call through
this module must go through asyncio.to_thread() at the call site (see
service.py), never awaited directly, or it blocks the event loop for
every other request.

The storage client uses HTTP on the internal Docker network. Public download
signing uses a separate HTTPS endpoint when configured; its proxy must preserve
Host, path and query. The application nginx configuration does not provision
that storage hostname. Do not hand a browser an internal minio:9000 URL.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException
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


def get_download_client() -> Minio:
    """Sign for the browser-facing host, without making a public network call.

    Region is explicit so the SDK does not probe the external hostname for
    bucket location while signing. It must match the deployed MinIO region.
    Local development retains the existing direct-storage fallback only.
    """
    settings = get_settings()
    endpoint = settings.minio_public_endpoint
    unavailable = "File downloads need a public HTTPS storage endpoint and region configuration."
    if not endpoint:
        if settings.environment.lower() in {"production", "prod"}:
            raise HTTPException(503, unavailable)
        return get_minio_client()
    try:
        parsed = urlsplit(f"https://{endpoint}")
        if (endpoint != endpoint.strip() or not parsed.hostname or parsed.path
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or not settings.minio_region.strip()):
            raise HTTPException(503, unavailable)
        return Minio(endpoint, access_key=settings.minio_root_user,
                     secret_key=settings.minio_root_password,
                     secure=True, region=settings.minio_region)
    except ValueError:
        raise HTTPException(503, unavailable) from None


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
