```markdown
# Security Policy

## Supported Versions

Only the latest release and the current active integration branches receive active security updates and vulnerability patches.

| Version / Branch | Supported          | Notes |
| ---------------- | ------------------ | ----- |
| `main`           | :white_check_mark: | Production releases |
| `staging`        | :white_check_mark: | Active integration branch |
| `< 1.0.0` / legacy tags | :x:        | End of life; upgrade immediately |

---

## Reporting a Vulnerability

The HealthDoc team takes the security and integrity of patient health records, hospital operations, and integration endpoints (including ABDM V3 and Keycloak IAM) seriously.

If you discover a security vulnerability in this project, **do not open a public issue or pull request.**

### Disclosure Channels

Please report security issues through one of the following private methods:

* **GitHub Security Advisory:** Submit a private report via the [Security Advisory tab](https://github.com/IUI-Solutions-HealthDoc/healthdoc/security/advisories/new).
* **Security Team Email:** Send details to `security@iuisolutions.com` (or the repository tech leads).

### What to Include in Your Report

To help us triage and resolve the issue quickly, include:

* A clear description of the vulnerability and its potential impact.
* Step-by-step reproduction instructions, a minimal Proof of Concept (PoC), or request traces.
* Affected components (e.g., `backend` FastAPI routes, `frontend` client/Electron, `infra` Nginx/Keycloak configs, database migrations).
* Any relevant environment details (e.g., local Docker Compose, staging, edge deployment).

---

## Response Process & SLAs

* **Initial Acknowledgment:** Within **48 hours** of report receipt.
* **Triage & Assessment:** Initial severity assessment and confirmation within **5 business days**.
* **Remediation & Patching:** High/critical vulnerabilities impacting patient data, ABDM compliance, or authentication are prioritized for expedited hotfixing on `staging` and backporting to `main`.
* **Public Disclosure:** Coordinated release and disclosure only after a validated patch is deployed and downstream instances have been notified.

---

## Compliance & Security Standards

HealthDoc HMIS is designed to adhere to Indian healthcare data protection standards and security frameworks:

* **ABDM V3 Alignment:** Secure handling of Health IDs, consent artifacts, and FHIR bundles via sandbox/gateway protocols.
* **DPDP Act Compliance:** Digital Personal Data Protection principles governing patient PII/PHI access controls, audit logging, and data retention.
* **WASA / Cert-In Guidelines:** Regular web application security assessment mitigations (mitigating injection flaws, broken access control, and insecure direct object references).
* **Edge & Cloud Security:** Encrypted transit (TLS 1.3) and encrypted storage at rest for local SQLite/PostgreSQL sync caches and cloud stores.

---

## Prohibited Actions

When conducting security research on HealthDoc deployments:

* Do not perform Denial of Service (DoS/DDoS) attacks against staging or live endpoints.
* Do not access, modify, or leak real patient records or personal identifiable information (PII).
* Do not execute destructive actions against shared testing databases.

```
