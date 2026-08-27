# Security Policy

## Supported Versions

Only the latest release and the current active integration branches receive
active security updates and vulnerability patches.

| Version / Branch | Supported | Notes |
| ---------------- | --------- | ----- |
| `main` | :white_check_mark: | Production releases |
| `staging` | :white_check_mark: | Active integration branch |
| `< 1.0.0` / legacy tags | :x: | End of life; upgrade immediately |

---

## Reporting a Vulnerability

The HealthDoc team takes the security and integrity of patient health records,
hospital operations, and integration endpoints (including ABDM V3 and Keycloak
IAM) seriously.

If you discover a security vulnerability in this project, **do not open a
public issue or pull request.**

### Disclosure Channels

* **GitHub Security Advisory:** submit a private report via the
  [Security Advisory tab](https://github.com/IUI-Solutions-HealthDoc/healthdoc/security/advisories/new).
* **Security Team Email:** `security@iuisolutions.com`.

### What to Include

* A clear description of the vulnerability and its potential impact.
* Reproduction steps, a minimal proof of concept, or request traces.
* Affected components — `backend` FastAPI routes, `frontend` client/Electron,
  `infra` Nginx/Keycloak configs, or database migrations.
* Environment details: local Docker Compose, staging, or edge deployment.

---

## Response Process

* **Initial acknowledgment:** within 48 hours.
* **Triage and severity assessment:** within 5 business days.
* **Remediation:** high and critical issues affecting patient data, ABDM
  compliance or authentication are hotfixed on `staging` and backported to
  `main`.
* **Public disclosure:** coordinated, after a validated patch is deployed and
  downstream instances have been notified.

---

## Security Controls

Stated as implemented, not as aspiration. A security policy is a
representation: an assessor who reads a claim here and cannot find it in the
code treats the gap as a misstatement, which is worse than never having made
the claim. Anything not yet true belongs in the roadmap, not this file.

**Transport.** TLS 1.3 only (`infra/nginx/prod-conf.d`). HSTS with
`includeSubDomains`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
`Permissions-Policy`, and a Content-Security-Policy with `frame-ancestors 'none'`.

**Data at rest.** Sensitive identifiers and credentials are encrypted at the
COLUMN level with AES-GCM, key-versioned to support rotation — Aadhaar numbers
and ABDM linking tokens among them. Aadhaar is additionally stored as an HMAC
blind index and never in plaintext.

To be precise about scope, because the distinction is one an auditor will draw:
this is application-level field encryption. Full-disk or tablespace encryption
of the database volume is a **deployment** responsibility and is not configured
by this repository. Operators handling production data should enable it at the
storage layer.

**Authentication.** Keycloak OIDC. Access tokens are verified against JWKS with
the signing key selected by `kid`; `exp`, `iat` and `sub` are required. Tokens
are held in memory client-side — never in cookies or `localStorage`. Brute-force
protection and account lockout are enforced at the realm; MFA (TOTP) is
mandatory in production builds of the realm.

**Access control.** Every clinical record is scoped to its facility. A request
for another facility's record returns 404 rather than 403 — a 403 confirms the
record exists and is an enumeration oracle.

**Audit.** `audit_logs` is append-only with per-facility hash chaining, enforced
by database triggers: update and delete raise.

**Dependencies.** `make audit-deps` runs `pip-audit` and `npm audit`. The gate is
zero known vulnerabilities.

---

## Compliance Alignment

* **ABDM V3** — ABHA identity flows, with Aadhaar and OTP values RSA-encrypted
  before transmission to the gateway.
* **DPDP Act 2023** — consent records, grievance handling, a named Data
  Protection Officer, and data-access logging.
* **CERT-In / WASA** — assessed against the NHA Web Application Security
  Assessment checklist; see `docs/wasa-readiness.md` for current status,
  including findings that remain open.

---

## Prohibited Actions

When conducting security research on HealthDoc deployments:

* Do not perform denial-of-service attacks against staging or live endpoints.
* Do not access, modify or exfiltrate real patient records or personal data.
* Do not execute destructive actions against shared testing databases.
