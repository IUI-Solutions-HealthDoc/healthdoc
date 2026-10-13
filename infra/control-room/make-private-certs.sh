#!/bin/sh
# Certificates for the private link between the hospital server and the
# control-room server (docs/control-room-design-2026-10-10.md, "Encryption").
#
#   infra/control-room/make-private-certs.sh <out-dir> <hospital-private-ip> [name]
#
# Makes a private CA and one server certificate for the hospital server, used by
# its PostgreSQL (5432) and Keycloak (8443). The certificate names both the
# private IP (what the control-room API connects to) and a DNS name, default
# healthdoc-private (what the control-room nginx verifies; nginx checks names,
# not IP addresses).
#
# Copy to the hospital server:      private-server.crt, private-server.key
# Copy to the control-room server:  private-ca.crt   (never the CA key)
# Keep private-ca.key offline. Re-run with a new out-dir to rotate.
set -eu

OUT=${1:?usage: make-private-certs.sh <out-dir> <hospital-private-ip> [name]}
IP=${2:?hospital private IP required}
NAME=${3:-healthdoc-private}
DAYS=${DAYS:-825}

case "$IP" in
  *[!0-9.]*|"") echo "not an IPv4 address: $IP" >&2; exit 2 ;;
esac
if [ -e "$OUT/private-ca.key" ]; then
  echo "$OUT already holds a CA; use a new directory to rotate" >&2
  exit 2
fi
mkdir -p "$OUT"
umask 077

openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days "$DAYS" \
  -keyout "$OUT/private-ca.key" -out "$OUT/private-ca.crt" \
  -subj "/CN=HealthDoc private CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null

openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$OUT/private-server.key" -out "$OUT/private-server.csr" \
  -subj "/CN=$NAME" 2>/dev/null

cat > "$OUT/private-server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$NAME,IP:$IP
EOF
openssl x509 -req -sha256 -days "$DAYS" -in "$OUT/private-server.csr" \
  -CA "$OUT/private-ca.crt" -CAkey "$OUT/private-ca.key" -CAcreateserial \
  -extfile "$OUT/private-server.ext" -out "$OUT/private-server.crt" 2>/dev/null
rm -f "$OUT/private-server.csr" "$OUT/private-server.ext" "$OUT/private-ca.srl"
chmod 644 "$OUT/private-ca.crt" "$OUT/private-server.crt"

openssl verify -CAfile "$OUT/private-ca.crt" "$OUT/private-server.crt"
echo "server certificate names: DNS:$NAME IP:$IP"
