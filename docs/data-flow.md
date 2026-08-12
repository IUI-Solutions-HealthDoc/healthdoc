# HealthDoc data-flow diagram (BA-W8-01)

Rendered diagram: [architecture.html](architecture.html) (context, request lifecycle, and
workflows). This file is the text description for the security/ISMS annex.

## Trust boundaries

1. **Public internet to Nginx edge** — the intended deployment terminates TLS 1.3 here and
   exposes only 443.
2. **Nginx to app tier** — FastAPI, Next.js, and Keycloak run on the internal Docker network.
3. **App to data tier** — Postgres, Mongo, Redis, MinIO, and Orthanc should have no public port.
4. **Facility edge to cloud** — outbox sync and mTLS are planned; #309 adds only the local
   transactional outbox.
5. **App to ABDM Gateway** — outbound HTTPS targets the ABDM V3 gateway.

## Sensitive data paths

- Aadhaar/ABHA linking token: #303 encrypts values with AES-256-GCM before persistence and
  derives an HMAC blind index. Key version is stored, but rotation is not complete until old
  versions can be loaded on read.
- Clinical reads: role and consent gating exist at different stages of delivery;
  `data_access_log` coverage for every read, including break-glass, is planned in #266.
- Mutations: the intended design is a business write, audit record, and outbox event in one
  transaction. Audit sealing/signing and the outbox migration are still pending.

## Data at rest / in transit

- At rest: encrypted Postgres volumes and MinIO buckets are deployment goals, not verified
  controls in the checked-in infrastructure configuration.
- In transit: the intended edge uses TLS 1.3; mTLS for edge-to-cloud sync is planned; ABDM
  traffic uses HTTPS.
