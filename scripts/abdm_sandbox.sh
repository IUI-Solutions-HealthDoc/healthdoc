#!/usr/bin/env bash
# ABDM sandbox bring-up — the three steps in NHA's onboarding email, run from
# your own .env so the client secret never leaves this machine.
#
#   ./scripts/abdm_sandbox.sh token
#   ./scripts/abdm_sandbox.sh set-url https://your-public-host
#   ./scripts/abdm_sandbox.sh add-hip  SERVICE_ID "Facility Name" https://your-public-host
#   ./scripts/abdm_sandbox.sh add-hiu  SERVICE_ID "Facility Name" https://your-public-host
#   ./scripts/abdm_sandbox.sh services
#
# Reads ABDM_CLIENT_ID / ABDM_CLIENT_SECRET / ABDM_X_CM_ID from .env. The secret
# is never echoed, never passed on a command line (where `ps` would show it),
# and never written to a log — it goes into the request body and nowhere else.
#
# WHY A SCRIPT AND NOT THE CURL COMMANDS FROM THE EMAIL
# The emailed curls omit the Authorization header entirely, so they 401 as
# written: bridge management still needs a session token. They also omit
# REQUEST-ID, TIMESTAMP and X-CM-ID, which the gateway rejects requests
# without. This gets a token first and sends all four.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo "no .env — copy .env.example first"; exit 1; }
# shellcheck disable=SC1091
set -a; source .env; set +a

GATEWAY="${ABDM_GATEWAY_BASE_URL:-https://dev.abdm.gov.in}"
CM_ID="${ABDM_X_CM_ID:-sbx}"
SESSION_PATH="${ABDM_SESSION_PATH:-/api/hiecm/gateway/v3/sessions}"
BRIDGE="$GATEWAY/gateway/v1/bridges"

for v in ABDM_CLIENT_ID ABDM_CLIENT_SECRET; do
  val="${!v:-}"
  if [[ -z "$val" || "$val" == "change-me" ]]; then
    echo "✗ $v is not set in .env."
    echo "  Set it from the NHA onboarding email, then re-run. Do not commit .env."
    exit 1
  fi
done

_now() { date -u +"%Y-%m-%dT%H:%M:%S.000Z"; }

token() {
  local rid body http
  rid=$(uuidgen)
  # Built here and piped in via --data @-, so the secret never appears on the
  # process list where `ps` would show it to any other user on the box.
  body=$(printf '{"clientId":"%s","clientSecret":"%s","grantType":"client_credentials"}' \
          "$ABDM_CLIENT_ID" "$ABDM_CLIENT_SECRET")
  http=$(printf '%s' "$body" | curl -s -o /tmp/abdm_session.$$ -w '%{http_code}' \
    -X POST "$GATEWAY$SESSION_PATH" \
    -H "REQUEST-ID: $rid" -H "TIMESTAMP: $(_now)" -H "X-CM-ID: $CM_ID" \
    -H "Content-Type: application/json" -H "Accept: application/json" \
    --data @-)
  if [[ "$http" != "200" && "$http" != "202" ]]; then
    echo "✗ session request returned HTTP $http" >&2
    # Body may echo the client id; show it only on failure, and say so.
    sed 's/"clientSecret":"[^"]*"/"clientSecret":"[redacted]"/g' /tmp/abdm_session.$$ >&2
    rm -f /tmp/abdm_session.$$; exit 1
  fi
  # accessToken is the v3 field; some responses use access_token.
  python3 -c "import json,sys;d=json.load(open('/tmp/abdm_session.$$'));print(d.get('accessToken') or d.get('access_token') or '')"
  rm -f /tmp/abdm_session.$$
}

_auth_call() {  # method path json
  local tok rid
  tok=$(token)
  [[ -n "$tok" ]] || { echo "✗ no token in session response" >&2; exit 1; }
  rid=$(uuidgen)
  curl -s -X "$1" "$2" \
    -H "Authorization: Bearer $tok" \
    -H "REQUEST-ID: $rid" -H "TIMESTAMP: $(_now)" -H "X-CM-ID: $CM_ID" \
    -H "Content-Type: application/json" -H "Accept: */*" \
    ${3:+--data "$3"} -w '\n[HTTP %{http_code}]\n'
}

case "${1:-}" in
  token)
    t=$(token)
    if [[ -n "$t" ]]; then
      echo "✓ session token obtained (${#t} chars). Credentials work."
    else
      echo "✗ no token field in the response"; exit 1
    fi
    ;;
  set-url)
    [[ -n "${2:-}" ]] || { echo "usage: $0 set-url https://your-public-host"; exit 1; }
    [[ "$2" == https://* ]] || { echo "✗ ABDM requires https with a valid certificate"; exit 1; }
    echo "PATCH $BRIDGE  url=$2"
    _auth_call PATCH "$BRIDGE" "{\"url\":\"$2\"}"
    ;;
  add-hip|add-hiu)
    kind=$([[ "$1" == "add-hip" ]] && echo HIP || echo HIU)
    [[ -n "${4:-}" ]] || { echo "usage: $0 $1 SERVICE_ID \"Facility Name\" https://your-public-host"; exit 1; }
    echo "POST $BRIDGE/addUpdateServices  type=$kind id=$2"
    _auth_call POST "$BRIDGE/addUpdateServices" \
      "[{\"id\":\"$2\",\"name\":\"$3\",\"type\":\"$kind\",\"active\":true,\"alias\":[\"$2\"],\"endpoints\":[{\"address\":\"$4\",\"connectionType\":\"https\",\"use\":\"registration\"}]}]"
    ;;
  services)
    echo "GET $BRIDGE/getServices"
    _auth_call GET "$BRIDGE/getServices"
    ;;
  *)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
