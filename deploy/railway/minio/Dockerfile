# MinIO for Railway. Build context: repository root.
#
# Same pinned source build as infra/minio/Dockerfile.source (keep MINIO_REF
# and the version flags identical to it: changing them is a storage upgrade).
# It differs only in carrying its own CMD, because a Railway start command
# would replace the entrypoint and the volume path must be given here.
FROM golang:1.24-bookworm AS build
ARG MINIO_REF=07c3a429bfed433e49018cb0f78a52145d4bedeb
ENV CGO_ENABLED=0
RUN go install -ldflags="-s -w \
    -X github.com/minio/minio/cmd.Version=2025-09-07T16:13:09Z \
    -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-09-07T16-13-09Z \
    -X github.com/minio/minio/cmd.CommitID=${MINIO_REF} \
    -X github.com/minio/minio/cmd.ShortCommitID=07c3a429bfed \
    -X github.com/minio/minio/cmd.CopyrightYear=2025" \
    github.com/minio/minio@${MINIO_REF}

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /go/bin/minio /usr/local/bin/minio
EXPOSE 9000 9001
# Attach a Railway volume at /data. ":9000" listens on IPv4 and IPv6, which
# Railway's private network needs.
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--address", ":9000", "--console-address", ":9001"]
