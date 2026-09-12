# MinIO image provenance and CI recovery

On 12 September 2026, PRs #553 and #554 failed before backend/browser tests
could execute: Docker Hub denied the pull of `minio/minio:latest`. Both the
standalone CI service and Compose used that mutable image reference.

CI, development and production Compose now use the official Quay registry
with immutable **multi-platform manifest** digests. These are the same artifacts
already cached on the development machine, not a MinIO version or disk-format
upgrade:

| Component | Manifest digest |
|---|---|
| `quay.io/minio/minio` | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` |
| `quay.io/minio/mc` | `sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727` |

The registry manifest includes Linux amd64 (GitHub runners) and arm64 (local
Mac). The cached server reports `RELEASE.2025-09-07T16-13-09Z`, commit
`07c3a429bfed433e49018cb0f78a52145d4bedeb`. Pin updates must be coordinated in
both Compose files and CI; `backend/tests/test_minio_image_pins.py` detects
registry regressions, mutable tags and mismatched server/client pins.

The existing health checks, real MinIO file tests, bucket initialization and
browser gates are unchanged. No data volumes are replaced or deleted by this
patch. Do not run `docker compose down -v` to apply it.

## Separate production lifecycle work

This repairs image availability; it is **not a security upgrade or a claim
that this legacy release is currently vulnerability-free**. MinIO's community
README now describes source-only distribution and legacy binaries that no
longer receive updates. A supported object-store strategy, vulnerability
review, source-build/update policy and backup-tested rollout remain separate
production requirements. Do not replace MinIO with an unverified third-party
image or bypass file tests to make CI green.

Sources checked for this repair:

- [Official container instructions using Quay](https://github.com/minio/minio/blob/master/docs/docker/README.md)
- [Official source-only distribution notice](https://github.com/minio/minio#source-only-distribution)

Registry evidence can be rechecked with `docker buildx imagetools inspect`
against each digest above, without starting a container or touching storage.
