# ISMS asset inventory (BA-W8-01)

| # | Asset | Type | Classification | Owner | Status | Controls / delivery state |
|---|-------|------|----------------|-------|--------|---------------------------|
| 1 | PostgreSQL (system of record) | Data store | Restricted (PHI+PII) | B1 | Partial | TLS/RBAC and backups are deployment controls; encrypted volume is planned and must not be assumed. |
| 2 | MongoDB (clinical notes, FHIR, ABDM payloads) | Data store | Restricted | B1 | Partial | Internal-only and TLS/backups are deployment controls to verify per environment. |
| 3 | Redis (queue state, cache, pub/sub) | Cache/broker | Internal | B1 | Partial | Internal-only; no durable PHI by design. |
| 4 | MinIO (files, reports, audit archives) | Object store | Restricted | B7 | Pending | Private buckets, presigned URLs, and access logging land with the files module. |
| 5 | Orthanc PACS (DICOM) | Imaging store | Restricted | B5 | Pending | Authentication and internal-only deployment must be verified. |
| 6 | Keycloak (identity) | IAM | Restricted (credentials) | B1 | Partial | Brute-force lockout is configured; MFA for admin/supervisor is planned. |
| 7 | FastAPI backend | Application | Confidential | B1 | Partial | JWT verification and envelope middleware exist; ABAC is pending #307 and audit middleware #266. |
| 8 | Next.js/Electron frontend | Application | Internal | F1 | Partial | CORS and route controls depend on deployment configuration. |
| 9 | Nginx edge | Network | Confidential | B1 | Partial | TLS/security headers/rate limits must be verified per deployed environment. |
| 10 | ABDM Gateway credentials | Secret | Restricted | B1 | Partial | Environment/secret-manager handling is required; never store credentials in the repo. |
| 11 | Crypto keys (Aadhaar/ABHA AES+HMAC) | Secret | Restricted | B1/B2 | Pending | #303 validates current keys; versioned rotation is partial because old versions are not loaded. |
| 12 | Audit log chain | Data/integrity | Restricted | B7 | Planned | Columns exist in 0003, but the sealer/signing job has no owner and is not implemented. |
| 13 | Outbox / edge-cloud sync | Data pipeline | Restricted | B1 | Pending | #309 supplies the local outbox; mTLS and conflict rules are not yet operating controls. |
| 14 | CI/CD (GitHub Actions) | Pipeline | Confidential | B1 | Partial | Branch protection and CODEOWNERS are active; a ZAP scan is planned, not present. |

Classification key: Restricted (health/PII/secrets) > Confidential (system integrity) >
Internal > Public. Review cadence: each release.
