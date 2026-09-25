"""Idempotently provision private MinIO buckets without a second registry image."""

from __future__ import annotations

import os

from minio import Minio


def provision_private_buckets(client: Minio, names: tuple[str, ...]) -> None:
    for name in names:
        if not client.bucket_exists(name):
            client.make_bucket(name)
        # Equivalent to `mc anonymous set none`; existing buckets must not
        # retain an accidental public policy after a container replacement.
        client.delete_bucket_policy(name)


def main() -> None:
    endpoint = os.environ["MINIO_ENDPOINT"]
    user = os.environ["MINIO_ROOT_USER"]
    password = os.environ["MINIO_ROOT_PASSWORD"]
    names = (
        os.environ.get("MINIO_BUCKET_FILES", "hd-files"),
        os.environ.get("MINIO_BUCKET_REPORTS", "hd-reports"),
    )
    if not all(names) or names[0] == names[1]:
        raise SystemExit("MinIO bucket names must be distinct and non-empty")
    client = Minio(endpoint, access_key=user, secret_key=password, secure=False)
    provision_private_buckets(client, names)
    print("Private MinIO buckets ready")


if __name__ == "__main__":
    main()
