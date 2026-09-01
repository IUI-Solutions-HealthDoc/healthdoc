#!/usr/bin/env bash
# ABDM sandbox bring-up — the three steps in NHA's onboarding email, run from
# your own .env so the client secret never leaves this machine.
#
#   ./scripts/abdm_sandbox.sh token
#   ./scripts/abdm_sandbox.sh set-url https://your-public-host
#   ./scripts/abdm_sandbox.sh add-hip  SERVICE_ID "Facility Name" https://your-public-host
#   ./scripts/abdm_sandbox.sh add-hiu  SERVICE_ID "Facility Name" https://your-public-host
#   ./scripts/abdm_sandbox.sh services
#   ./scripts/abdm_sandbox.sh doctor  https://your-public-host
#   ./scripts/abdm_sandbox.sh cert
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
# Bridge management moved to v3. The old /gateway/v1/bridges answers 403
# "900908 API Subscription validation failed" for a sandbox client, which reads
# as a missing entitlement and cost a support round-trip to disprove — the v3
# routes below answer 200 with the SAME credentials and the same header set.
BRIDGE_SERVICES="$GATEWAY/api/hiecm/gateway/v3/bridge-services"
BRIDGE_SERVICE="$GATEWAY/api/hiecm/gateway/v3/bridge-service"
BRIDGE_URL="$GATEWAY/api/hiecm/gateway/v3/bridge/url"

# Credentials are checked per command, not up front: `doctor` is a pure
# reachability probe and is the thing you want to run BEFORE putting a secret
# on the machine. Requiring credentials for it would invert that order.
require_credentials() {
  local v val
  for v in ABDM_CLIENT_ID ABDM_CLIENT_SECRET; do
    val="${!v:-}"
    if [[ -z "$val" || "$val" == "change-me" ]]; then
      echo "✗ $v is not set in .env."
      echo "  Set it from the NHA onboarding email, then re-run. Do not commit .env."
      exit 1
    fi
  done
}

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
    require_credentials
    t=$(token)
    if [[ -n "$t" ]]; then
      echo "✓ session token obtained (${#t} chars). Credentials work."
    else
      echo "✗ no token field in the response"; exit 1
    fi
    ;;
  set-url)
    require_credentials
    [[ -n "${2:-}" ]] || { echo "usage: $0 set-url https://your-public-host"; exit 1; }
    [[ "$2" == https://* ]] || { echo "✗ ABDM requires https with a valid certificate"; exit 1; }
    echo "PATCH $BRIDGE_URL  url=$2"
    # 202 with an empty body is success here. Read it back to be sure.
    _auth_call PATCH "$BRIDGE_URL" "{\"url\":\"$2\"}"
    ;;
  add-hip|add-hiu)
    require_credentials
    kind=$([[ "$1" == "add-hip" ]] && echo HIP || echo HIU)
    [[ -n "${4:-}" ]] || { echo "usage: $0 $1 SERVICE_ID \"Facility Name\" https://your-public-host"; exit 1; }
    # v3 registers ONE service that may be HIP, HIU or both, rather than the
    # v1 array of typed entries. isHip/isHiu are booleans on a single record.
    is_hip=$([[ "$kind" == HIP ]] && echo true || echo false)
    is_hiu=$([[ "$kind" == HIU ]] && echo true || echo false)
    echo "PUT $BRIDGE_SERVICE  serviceId=$2 isHip=$is_hip isHiu=$is_hiu"
    _auth_call PUT "$BRIDGE_SERVICE" \
      "{\"bridgeId\":\"$ABDM_CLIENT_ID\",\"serviceId\":\"$2\",\"name\":\"$3\",\"isHip\":$is_hip,\"isHiu\":$is_hiu,\"isHealthLocker\":null,\"isPhr\":false,\"endpoints\":{},\"attributes\":null,\"active\":true}"
    ;;
  doctor)
    # Pre-flight: does this public URL actually reach OUR callback routes?
    # Registering a URL that does not is a wasted round-trip with NHA support,
    # and the failure shows up later as "the gateway says it called you" with
    # nothing in your logs.
    [[ -n "${2:-}" ]] || { echo "usage: $0 doctor https://your-public-host"; exit 1; }
    [[ "$2" == https://* ]] || { echo "✗ ABDM requires https"; exit 1; }
    base="${2%/}"
    fail=0
    for path in /api/v1/abdm/hip/callbacks/consent-notify \
                /api/v1/abdm/hip/callbacks/health-information/request \
                /api/v1/abdm/hiu/callbacks/health-information/transfer; do
      # No `|| echo 000` — curl already writes 000 to stdout when it cannot
      # connect, and the fallback appended a second one, producing "000000"
      # which then fell through to the "unexpected" branch and hid the real
      # diagnosis from the person reading it.
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
             -X POST "$base$path" -H 'Content-Type: application/json' -d '{}') || true
      [[ -n "$code" ]] || code=000
      case "$code" in
        503) verdict="reachable — refusing because ABDM_CALLBACK_SHARED_SECRET is unset (expected before setup)";;
        401) verdict="reachable — authenticating (secret is set)";;
        404) verdict="ROUTED SOMEWHERE ELSE — this host is not serving this app"; fail=1;;
        000) verdict="NO RESPONSE — tunnel down, or origin unreachable"; fail=1;;
        50*) verdict="origin error $code — check the backend logs"; fail=1;;
        200|202) verdict="ACCEPTED WITHOUT AUTH — investigate before registering this URL"; fail=1;;
        *)   verdict="unexpected $code"; fail=1;;
      esac
      printf '  %-58s %s\n' "${path#/api/v1}" "$verdict"
    done
    echo
    if [[ "$fail" == "0" ]]; then
      echo "✓ ABDM can reach every callback on $base"
      echo "  Register it:  $0 set-url $base"
    else
      echo "✗ Not ready to register. ABDM would call this URL and get nothing usable."
      exit 1
    fi
    ;;
  cert)
    require_credentials
    # ABDM's PUBLIC certificate, used to RSA-encrypt Aadhaar numbers and OTPs.
    # Public key material, not a secret — but ABDM rotates it, which is why
    # this is a command rather than a value someone pasted once and forgot.
    #
    # VERIFIED 2026-08-31: this endpoint returns {"publicKey": "<base64 SPKI>"}
    # — a bare key, NOT a PEM block, so it is wrapped here. Feeding the raw
    # field to load_pem_public_key fails with an unhelpful parse error.
    tok=$(token)
    [[ -n "$tok" ]] || { echo "✗ no token" >&2; exit 1; }
    curl -s --max-time 25 "https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate" \
      -H "Authorization: Bearer $tok" -H "REQUEST-ID: $(uuidgen)" \
      -H "TIMESTAMP: $(_now)" -H "X-CM-ID: $CM_ID" > /tmp/abdm_cert.$$
    python3 - "$$" <<'PYEOF'
import json, sys, textwrap
raw = json.load(open(f"/tmp/abdm_cert.{sys.argv[1]}"))
key = (raw.get("publicKey") or "").strip()
if not key:
    print("✗ no publicKey in the response:", list(raw)[:4]); sys.exit(1)
pem = key if "BEGIN" in key else (
    "-----BEGIN PUBLIC KEY-----\n" + "\n".join(textwrap.wrap(key, 64)) + "\n-----END PUBLIC KEY-----")
print("Paste this line into .env (public key material, not a secret):\n")
# QUOTED. The PEM header contains spaces ("BEGIN PUBLIC KEY"), and an
# unquoted value breaks `source .env` — which the Makefile and this script
# both do, so an unquoted paste takes the whole toolchain down with
# "PUBLIC: command not found".
print('ABDM_PUBLIC_KEY_PEM="' + pem.replace("\n", "\\n") + '"')
print("\nThen: docker compose -f infra/docker-compose.yml --env-file .env up -d --force-recreate backend")
print("(`restart` reuses the old environment and will not pick this up.)")
PYEOF
    rm -f /tmp/abdm_cert.$$
    ;;
  services)
    require_credentials
    echo "GET $BRIDGE_SERVICES"
    _auth_call GET "$BRIDGE_SERVICES"
    ;;
  *)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
