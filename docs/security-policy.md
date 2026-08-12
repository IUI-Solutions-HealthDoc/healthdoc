# HealthDoc security policy (BA-W8-01)

Scope: the HealthDoc HMIS platform (edge + cloud). Framework: DPDP Act 2023, ABDM data
policies, CERT-In directions. (Not HIPAA — US law, out of scope.)

This document distinguishes implemented controls from work that is planned or blocked. A
planned control must not be treated as an operating control during an audit or incident.

## Control status

| Control | Status | Owner | Landing in |
|---|---|---|---|
| Aadhaar AES-256-GCM encryption and blind index | Pending review | B1 | #303 |
| Key-versioned key rotation | Partial — version is recorded; old versions are not yet loaded | B1 | — |
| ABAC policy enforcement | Pending merge | B1 | #307 |
| Clinical-read `data_access_log` | Planned | B7 | #266 (0004) |
| Break-glass endpoint | Planned — router is not registered | B1/B7 | 0004 and 0020 |
| Audit chain sealing and signatures | Planned — no owner assigned | — | — |
| Weekly OWASP ZAP baseline scan | Planned | B1 | — |
| MFA for admin and supervisor | Planned — not configured in Keycloak | B1 | — |

## Access control

- Authentication uses Keycloak (OIDC + PKCE), short-lived access tokens, and brute-force
  lockout. MFA (TOTP) for `admin` and `supervisor` is planned, not currently configured.
- Authorization uses RBAC (`require_roles`). The ABAC policy layer is pending merge in #307.
- Break-glass is designed to require MFA, a justification, a two-hour window, notifications,
  and review logging. It is not a live API until migrations 0004 and 0020 land.

## Data protection

- Aadhaar and ABHA linking tokens use the B1 encryption implementation in #303. It encrypts
  with AES-256-GCM and uses an HMAC blind index; key rotation remains partial until a
  version-to-key map is implemented.
- Files use private MinIO buckets and presigned URLs where the files module is deployed.
- Financial immutability, gapless numbering, and reversal-only corrections are enforced by the
  billing module as it is deployed.

## Accountability and monitoring

- Migration 0003 provides audit-log hash and signature columns. The sealing/signing job and its
  periodic integrity check are not implemented; no owner is assigned yet.
- Logging every clinical read to `data_access_log`, including denied and break-glass reads, is
  planned in #266 (migration 0004).
- An automated OWASP ZAP baseline scan is planned; no scheduled CI job exists yet.

## Network

- The intended deployment has a single TLS 1.3 Nginx ingress, security headers, restricted
  CORS origins, and no publicly exposed datastores. Deployment configuration must be verified
  per environment before it is relied upon as a control.

## Incident response (DPDP breach)

- CERT-In: report within 6 hours of detection.
- Data Protection Board: intimate without delay; detailed report within 72 hours.
- Affected patients: notify without delay. Tracking in `data_breach_notifications` is subject
  to the relevant schema landing.

## Review

This policy is reviewed each release; owner: B1 / Tech Lead.
