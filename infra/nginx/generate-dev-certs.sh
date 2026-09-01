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
# Override with LAN_IP=... when the address is not on en0.
LAN_IP="${LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')}"
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
