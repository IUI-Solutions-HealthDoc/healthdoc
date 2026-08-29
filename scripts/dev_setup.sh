#!/usr/bin/env bash
# HealthDoc one-command dev setup. Prerequisites: docker + docker compose v2, openssl.
set -euo pipefail

# Git Bash/MSYS rewrites POSIX-looking arguments before invoking Windows
# executables. That turns Keycloak's in-container path
# /opt/keycloak/bin/kcadm.sh into C:/Program Files/Git/opt/... and makes user
# provisioning fail even though Docker and Keycloak are healthy. The variable
# is ignored on macOS/Linux and keeps Docker arguments byte-for-byte on
# Windows.
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "docker not found — install Docker Desktop first"; exit 1; }
command -v openssl >/dev/null || { echo "openssl not found — install it first"; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit passwords before staging/prod use."
fi

read_env_value() {
  awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' .env
}

set_env_value() {
  local key="$1" value="$2" tmp
  tmp=$(mktemp)
  awk -F= -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    $1 == key { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' .env > "$tmp"
  mv "$tmp" .env
}

ensure_random_key() {
  local key="$1" current
  current=$(read_env_value "$key")
  case "$current" in
    ""|change-me|change-me-in-env|placeholder|test|dev)
      set_env_value "$key" "$(openssl rand -base64 32)"
      echo "Generated local $key"
      ;;
  esac
}

ensure_default() {
  local key="$1" value="$2" current
  current=$(read_env_value "$key")
  [[ -n "$current" ]] || set_env_value "$key" "$value"
}

ensure_random_key PII_ENCRYPTION_KEY
ensure_random_key AADHAAR_HMAC_KEY

# Correct the pre-auth-port issuer in existing local .env files without
# overwriting a deliberately configured external issuer.
case "$(read_env_value JWT_ISSUER)" in
  ""|http://keycloak:8080/realms/healthdoc|http://keycloak:8080/auth/realms/healthdoc)
    set_env_value JWT_ISSUER "https://localhost/auth/realms/healthdoc"
    ;;
esac
ensure_default JWT_JWKS_URL \
  "http://keycloak:8080/auth/realms/healthdoc/protocol/openid-connect/certs"
ensure_default NEXT_PUBLIC_KEYCLOAK_URL "https://localhost/auth"
ensure_default NEXT_PUBLIC_KEYCLOAK_REALM "healthdoc"
ensure_default NEXT_PUBLIC_OIDC_CLIENT_ID "healthdoc-frontend"

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

# Optional services run behind Compose profiles (schema §Module toggle behavior):
#   radiology -> orthanc (PACS, large image)   icd11 -> WHO ICD-API (several GB)
# Enable per facility:  COMPOSE_PROFILES=radiology,icd11 make setup
# Without them the app still works: radiology is simply off, and ICD search
# degrades to the local icd_codes catalog (never errors).
export COMPOSE_PROFILES="${COMPOSE_PROFILES:-}"
if [[ -n "$COMPOSE_PROFILES" ]]; then
  echo "Enabling optional profiles: $COMPOSE_PROFILES"
fi
docker compose -f infra/docker-compose.yml --env-file .env build
# Renew the frontend's anonymous .next cache after a build. node_modules is a
# named, nocopy volume and the container command refreshes it with npm ci;
# applying -V to the whole stack would needlessly recreate data services.
docker compose -f infra/docker-compose.yml --env-file .env up -d --renew-anon-volumes frontend
docker compose -f infra/docker-compose.yml --env-file .env up -d
# Nginx resolves Compose service names when its configuration is loaded. If a
# rebuilt backend/frontend gets a new container IP, a pre-existing proxy keeps
# the stale address until it is reloaded.
docker compose -f infra/docker-compose.yml --env-file .env restart nginx

HTTPS="${HTTPS_PORT:-443}"
BASE="https://localhost"
if [[ "$HTTPS" != "443" ]]; then BASE="https://localhost:$HTTPS"; fi
echo "Waiting for backend..."
BACKEND_READY=0
for i in $(seq 1 60); do
  if curl -ksf "$BASE/api/v1/health" >/dev/null 2>&1; then
    BACKEND_READY=1
    break
  fi
  sleep 2
done
if [[ "$BACKEND_READY" != "1" ]]; then
  echo "Backend did not become healthy. Recent logs:"
  docker compose -f infra/docker-compose.yml --env-file .env logs --tail=100 backend
  exit 1
fi

docker compose -f infra/docker-compose.yml --env-file .env exec -T backend alembic upgrade head

echo "Waiting for Keycloak..."
KEYCLOAK_READY=0
for i in $(seq 1 60); do
  if curl -sf "http://localhost:${KEYCLOAK_PORT:-8081}/auth/realms/healthdoc/.well-known/openid-configuration" >/dev/null 2>&1; then
    KEYCLOAK_READY=1
    break
  fi
  sleep 2
done
if [[ "$KEYCLOAK_READY" != "1" ]]; then
  echo "Keycloak did not become ready."
  exit 1
fi

kc() {
  docker compose -f infra/docker-compose.yml --env-file .env exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh "$@"
}

kc config credentials --server http://localhost:8080/auth --realm master \
  --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

ensure_keycloak_user() {
  local username="$1" first_name="$2" last_name="$3" roles="$4" subject role assigned
  subject=$(kc get users -r healthdoc -q exact=true -q username="$username" \
    --fields id --format csv --noquotes | tail -n 1)
  if [[ -z "$subject" ]]; then
    kc create users -r healthdoc -s username="$username" -s enabled=true \
      -s firstName="$first_name" -s lastName="$last_name" \
      -s email="$username@healthdoc.example" >/dev/null
  fi
  kc set-password -r healthdoc --username "$username" --new-password devpass >/dev/null
  # These are deterministic test identities, so their HealthDoc realm roles
  # must be exact. Merely adding roles let dev.admin retain the old supervisor
  # grant forever, which meant the "admin" smoke was also a records-authority
  # token and could hide an authorization defect.
  assigned=$(kc get-roles -r healthdoc --uusername "$username" \
    --fields name --format csv --noquotes)
  for role in superadmin receptionist doctor nurse lab_tech radiology_tech \
    pharmacist emergency hod supervisor admin auditor patient; do
    if [[ ",$roles," != *",$role,"* ]] && grep -Fxq "$role" <<< "$assigned"; then
      kc remove-roles -r healthdoc --uusername "$username" --rolename "$role" >/dev/null
    fi
  done
  IFS=',' read -r -a role_list <<< "$roles"
  for role in "${role_list[@]}"; do
    kc add-roles -r healthdoc --uusername "$username" --rolename "$role" >/dev/null
  done
  kc get users -r healthdoc -q exact=true -q username="$username" \
    --fields id --format csv --noquotes | tail -n 1
}

RECEPTIONIST_SUB=$(ensure_keycloak_user dev.receptionist Dev Receptionist receptionist)
DOCTOR_SUB=$(ensure_keycloak_user dev.doctor Dev Doctor doctor)
NURSE_SUB=$(ensure_keycloak_user dev.nurse Dev Nurse nurse)
LAB_TECH_SUB=$(ensure_keycloak_user dev.labtech Dev "Lab Technician" lab_tech)
RADIOLOGY_TECH_SUB=$(ensure_keycloak_user dev.radiology Dev "Radiology Technician" radiology_tech)
PHARMACIST_SUB=$(ensure_keycloak_user dev.pharmacist Dev Pharmacist pharmacist)
ADMIN_SUB=$(ensure_keycloak_user dev.admin Dev Admin admin)
AUDITOR_SUB=$(ensure_keycloak_user dev.auditor Dev Auditor auditor)
PATIENT_SUB=$(ensure_keycloak_user dev.patient Dev Patient patient)
# The HOD role had eight backend endpoints, a dashboard, and no way to log in as
# one — so none of it had ever been exercised by a human or a test.
HOD_SUB=$(ensure_keycloak_user dev.hod Dev "Head of Department" hod)
EMERGENCY_SUB=$(ensure_keycloak_user dev.emergency Dev "Emergency Registrar" emergency)
SUPERVISOR_SUB=$(ensure_keycloak_user dev.supervisor Dev "Records Supervisor" supervisor)
SUPERADMIN_SUB=$(ensure_keycloak_user dev.superadmin Dev "Platform Superadmin" superadmin)

# Do not print a successful setup banner if even one advertised login was not
# created. This explicit postcondition catches partial Keycloak bootstrap on
# every shell, including environments where `errexit` behaves unexpectedly
# inside command substitutions.
DEV_USERNAMES=(
  dev.receptionist dev.doctor dev.nurse dev.labtech dev.radiology
  dev.pharmacist dev.admin dev.auditor dev.patient dev.hod dev.emergency
  dev.supervisor dev.superadmin
)
for username in "${DEV_USERNAMES[@]}"; do
  subject=$(kc get users -r healthdoc -q exact=true -q username="$username" \
    --fields id --format csv --noquotes | tail -n 1)
  if [[ -z "$subject" ]]; then
    echo "Keycloak bootstrap incomplete: $username was not created."
    exit 1
  fi
done

docker compose -f infra/docker-compose.yml --env-file .env exec -T backend \
  python -m scripts.seed_dev_data \
    --user "dev.receptionist=$RECEPTIONIST_SUB" \
    --user "dev.doctor=$DOCTOR_SUB" \
    --user "dev.nurse=$NURSE_SUB" \
    --user "dev.labtech=$LAB_TECH_SUB" \
    --user "dev.radiology=$RADIOLOGY_TECH_SUB" \
    --user "dev.pharmacist=$PHARMACIST_SUB" \
    --user "dev.admin=$ADMIN_SUB" \
    --user "dev.auditor=$AUDITOR_SUB" \
    --user "dev.patient=$PATIENT_SUB" \
    --user "dev.hod=$HOD_SUB" \
    --user "dev.emergency=$EMERGENCY_SUB" \
    --user "dev.supervisor=$SUPERVISOR_SUB" \
    --user "dev.superadmin=$SUPERADMIN_SUB"

# ---------------------------------------------------------------------------
# Verify the OUTCOME, not just the absence of an error.
#
# A tester on Windows once finished this script with exit code 0 and seven of
# thirteen accounts. Git Bash was rewriting /opt/keycloak/bin/kcadm.sh into a
# Windows path, every kcadm call failed, and nothing checked. MSYS_NO_PATHCONV
# at the top of this file stops that particular cause, but the class of failure
# is what matters: any kcadm call that fails inside a command substitution or a
# pipeline can still leave a partial realm behind a successful exit.
#
# The cost of not checking is paid by the next person, and paid badly: a
# missing account presents at the login screen as a wrong password, so the
# tester blames themselves long before they suspect the setup script. Six roles
# silently absent is a day lost across a team.
#
# So count them. The banner below promises thirteen usable logins; this is what
# earns the right to print it.
# ---------------------------------------------------------------------------
expected_users="dev.receptionist dev.doctor dev.nurse dev.labtech dev.radiology \
dev.pharmacist dev.admin dev.auditor dev.patient dev.hod dev.emergency \
dev.supervisor dev.superadmin"

missing_users=""
for username in $expected_users; do
  found=$(kc get users -r healthdoc -q exact=true -q username="$username" \
    --fields username --format csv --noquotes 2>/dev/null | tail -n 1 || true)
  if [[ "$found" != "$username" ]]; then
    missing_users="$missing_users $username"
  fi
done

if [[ -n "$missing_users" ]]; then
  echo
  echo "SETUP FAILED: Keycloak is missing these accounts:$missing_users"
  echo
  echo "Every login for those roles will fail, and it will look like a wrong"
  echo "password rather than a broken setup. Do not start testing."
  echo
  echo "On Windows this is usually Git Bash path rewriting. Re-run with:"
  echo "  MSYS_NO_PATHCONV=1 bash ./scripts/dev_setup.sh"
  exit 1
fi

cat <<DONE

HealthDoc dev stack is up:
  App (via nginx)   $BASE            (self-signed cert — accept the warning)
  API health        $BASE/api/v1/health
  API docs          $BASE/api/v1/docs
  Keycloak admin    http://localhost:${KEYCLOAK_PORT:-8081}/auth   (admin / see .env)
  MinIO console     http://localhost:${MINIO_CONSOLE_PORT:-9001}
  Orthanc           http://localhost:${ORTHANC_PORT:-8042}
  Postgres localhost:${POSTGRES_PORT:-5432} · Mongo localhost:${MONGO_PORT:-27017} · Redis localhost:${REDIS_PORT:-6379}

Dev logins (Keycloak realm 'healthdoc', password 'devpass'):
  dev.receptionist / dev.doctor / dev.nurse / dev.labtech /
  dev.radiology / dev.pharmacist / dev.admin / dev.auditor / dev.patient / dev.hod /
  dev.emergency / dev.supervisor / dev.superadmin
DONE
