#!/usr/bin/env bash
# HealthDoc one-command dev setup. Prerequisites: docker + docker compose v2, openssl.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "docker not found — install Docker Desktop first"; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit passwords before staging/prod use."
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

# --- Port conflict pre-check -------------------------------------------------
declare -a CHECKS=(
  "POSTGRES_PORT:${POSTGRES_PORT:-5432}:Postgres"
  "MONGO_PORT:${MONGO_PORT:-27017}:MongoDB"
  "REDIS_PORT:${REDIS_PORT:-6379}:Redis"
  "KEYCLOAK_PORT:${KEYCLOAK_PORT:-8081}:Keycloak"
  "MINIO_PORT:${MINIO_PORT:-9000}:MinIO"
  "MINIO_CONSOLE_PORT:${MINIO_CONSOLE_PORT:-9001}:MinIO console"
  "ORTHANC_PORT:${ORTHANC_PORT:-8042}:Orthanc"
  "ORTHANC_DICOM_PORT:${ORTHANC_DICOM_PORT:-4242}:Orthanc DICOM"
  "BACKEND_PORT:${BACKEND_PORT:-8000}:Backend"
  "FRONTEND_PORT:${FRONTEND_PORT:-3000}:Frontend"
  "HTTP_PORT:${HTTP_PORT:-80}:Nginx HTTP"
  "HTTPS_PORT:${HTTPS_PORT:-443}:Nginx HTTPS"
)
BUSY=0
OWN_STACK=$(docker compose -f infra/docker-compose.yml --env-file .env ps -q 2>/dev/null | head -1 || true)
for entry in "${CHECKS[@]}"; do
  var="${entry%%:*}"; rest="${entry#*:}"; port="${rest%%:*}"; name="${rest#*:}"
  # if our own stack is already (partly) running, its ports are not conflicts
  if [[ -n "$OWN_STACK" ]]; then
    continue
  fi
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    proc=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN | awk 'NR==2{print $1" (pid "$2")"}')
    suggest=$((port + 30000)); [[ "$suggest" -gt 65535 ]] && suggest=$((port - 20000))
    echo "✗ Port $port ($name) is in use by: $proc"
    echo "    → either stop that process, or add to .env:  $var=$suggest"
    BUSY=1
  fi
done
if [[ "$BUSY" == "1" ]]; then
  echo ""
  echo "Fix the port conflicts above, then re-run: make setup"
  exit 1
fi
# -----------------------------------------------------------------------------

if [[ ! -f infra/nginx/certs/dev.crt ]]; then
  ./infra/nginx/generate-dev-certs.sh
fi

docker compose -f infra/docker-compose.yml --env-file .env up -d --build

HTTPS="${HTTPS_PORT:-443}"
BASE="https://localhost"
if [[ "$HTTPS" != "443" ]]; then BASE="https://localhost:$HTTPS"; fi
echo "Waiting for backend..."
for i in $(seq 1 60); do
  curl -ksf "$BASE/api/v1/health" >/dev/null 2>&1 && break
  sleep 2
done

docker compose -f infra/docker-compose.yml --env-file .env exec -T backend alembic upgrade head || \
  echo "Migration step failed — run 'make migrate' once backend is up."

cat <<DONE

HealthDoc dev stack is up:
  App (via nginx)   $BASE            (self-signed cert — accept the warning)
  API health        $BASE/api/v1/health
  API docs          $BASE/api/v1/docs
  Keycloak admin    http://localhost:${KEYCLOAK_PORT:-8081}/auth   (admin / see .env)
  MinIO console     http://localhost:${MINIO_CONSOLE_PORT:-9001}
  Orthanc           http://localhost:${ORTHANC_PORT:-8042}
  Postgres localhost:${POSTGRES_PORT:-5432} · Mongo localhost:${MONGO_PORT:-27017} · Redis localhost:${REDIS_PORT:-6379}

Dev logins (Keycloak realm 'healthdoc'): dev.receptionist / dev.doctor / dev.admin — password 'devpass'
DONE
