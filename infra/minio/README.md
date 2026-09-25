# MinIO source build and deployment safety

The former `quay.io/minio/minio` and `quay.io/minio/mc` pinned manifests no
longer allow fresh anonymous pulls, so CI stopped before running tests. CI,
development and production Compose now build `Dockerfile.source` at upstream
commit `07c3a429bfed433e49018cb0f78a52145d4bedeb`, corresponding to the
`RELEASE.2025-09-07T16-13-09Z` version of the already-running local server.
This is a source-equivalent build, **not a byte-for-byte identical binary**.
The Python MinIO SDK in the backend image creates the two private buckets;
no separate `mc` image is pulled.

For a new development install, `make setup` builds the image automatically.
Do not run `docker compose down -v`: that deletes object and database volumes.
Before changing an existing production server, back up and restore-test its
MinIO objects/configuration, build and inspect this image, then rehearse the
replacement against a copy of the volume. A change of upstream ref is a
separate storage upgrade and needs its own rollout plan.

This availability repair is **not** a claim that the old MinIO release is
currently vulnerability-free or suitable as a long-term production artifact.
Track a maintained object-store distribution and security review separately.
See the [official source-only notice](https://github.com/minio/minio#source-only-distribution).
