#!/usr/bin/env bash
# Self-signed cert for local dev only. Never use in staging/prod.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$DIR"

# The LAN address is a SAN as well as localhost, so the certificate still
# matches when the stack is reached from another machine — a multi-station
# demo, where each role sits at its own PC.
#
# Without it every other PC gets a NAME MISMATCH rather than the ordinary
# self-signed warning: a different, scarier dialog that some managed browsers
# refuse to let the user click through at all.
#
# Override with LAN_IP=... when the address is not on en0. Autodetection is
# best-effort: on hosts with neither macOS ipconfig nor GNU hostname -I, a
# localhost-only certificate is still a valid development fallback.
# Windows Git Bash has an `ipconfig` too, which rejects "getifaddr en0" with a
# usage text; only an IPv4 address is accepted from any of these (QA 12 Oct 2026).
detect_lan_ip() {
  local ip=""
  case "$(uname -s)" in
    Darwin) ip=$(ipconfig getifaddr en0 2>/dev/null || true) ;;
    Linux) ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true) ;;
    MINGW*|MSYS*|CYGWIN*)
      ip=$(ipconfig 2>/dev/null | tr -d '\r' | awk -F': ' '/IPv4/ {print $2; exit}' || true) ;;
  esac
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "$ip" || true
}
LAN_IP="${LAN_IP:-$(detect_lan_ip)}"
SAN="DNS:localhost,IP:127.0.0.1"
if [[ -n "${LAN_IP:-}" ]]; then
  SAN="$SAN,IP:$LAN_IP"
  echo "Including LAN address $LAN_IP in the certificate"
fi

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$DIR/dev.key" -out "$DIR/dev.crt" \
  -subj "/CN=localhost/O=HealthDoc Dev" \
  -addext "subjectAltName=$SAN"
echo "Wrote $DIR/dev.crt and dev.key"
