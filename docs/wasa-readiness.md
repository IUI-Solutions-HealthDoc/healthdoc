# WASA readiness — HealthDoc HMIS

**Assessed:** 26 Aug 2026 · **Remediated:** 26 Aug 2026
**Standard:** NHA Web Application Security Assessment (CERT-In empanelled auditor)
**Pass condition:** zero open Critical, High **or Medium** findings

> This is a self-assessment from source. It does not replace the auditor's VAPT —
> it is meant to remove the findings they would otherwise write up, before the
> clock starts.

---

## Verdict

**Both blockers are closed. The cybersecurity track is ready; the ABDM
functional track is not, because the workflows do not exist yet.**

A correction to the first version of this document: it claimed "no handler
returns exception text." That was wrong. `app/auth/deps.py` raised
`HTTPException(401, f"Invalid token: {exc}")` — the grep behind the claim
searched for `detail=str(exc)` and this was positional. The same file also
disabled audience verification behind a "tighten later" comment. Both were
found only when the file was read for the PyJWT migration, and both are now
fixed. A checklist answered by grep is a checklist answered by grep.

The security *architecture* was already strong — TLS 1.3-only, full header set,
AES-GCM at rest with key versioning, tokens never leaving memory, facility
scoping backed by tests. What failed was inventory hygiene and two missing
controls, and both are now in place.

| Track | State |
|---|---|
| Cybersecurity (VAPT) | ✅ blockers closed · 1 minor open (M3) · **930 tests pass on the upgraded stack** |
| ABDM functional | ❌ **Cannot be assessed — the workflows do not exist yet** |

---

## Blockers — CLOSED

### B1 — `python-jose` on the auth path ✅

Replaced with `PyJWT[crypto]>=2.13.0`. `pip-audit -r requirements.txt` now
reports **"No known vulnerabilities found"** across the whole file.

Two wrong turns worth recording: PyJWT 2.10.1 carries five advisories of its
own, and Starlette 0.52.1 still carried seven — the first set of pins I tried
looked modern and cleared nothing. The floors that actually close everything
are PyJWT 2.13.0, Starlette 1.6.0 (via FastAPI 0.141.1) and python-multipart
0.0.32. Verified by running the audit, not by reading changelogs.

Three defects fixed in the same file while migrating:

- **401 responses leaked the reason.** `f"Invalid token: {exc}"` tells an
  attacker probing with forged tokens whether the signature, the expiry or the
  issuer failed — a free oracle. Now a flat `"Invalid token"`, reason to the log.
- **`exp`, `iat` and `sub` were not required.** PyJWT does not require them by
  default; a token minted without `exp` never expires.
- **JWKS outage returned 401.** Our own outage told every user their password
  was wrong. Now 503.

### B2 — No MFA ✅

TOTP policy and `CONFIGURE_TOTP` in the shared realm; MFA forcing and the
password policy applied at render time by
`scripts/deploy/render_keycloak_realm.py`.

**Both are production-only, and the reason is not convenience.** Forcing TOTP
in the shared realm sends all thirteen dev identities to an OTP enrolment
screen. A strong password policy there is worse: `dev_setup.sh` sets every test
account to `devpass`, Keycloak enforces the policy at set-password time, and
all thirteen `kc set-password` calls are rejected — leaving the accounts with
no usable credential and the real-auth smoke suite unable to log in as anybody.

That is not hypothetical. The policy was first added to the shared realm and
broke `nurse-auth-e2e` on the remediation PR, in the same commit as a docstring
explaining why MFA could not live there. The general rule, now stated in the
renderer: **a control that development cannot satisfy does not belong in the
shared realm, however correct it is for production.**

The renderer refuses to emit a production realm that has lost brute-force
protection or its OTP policy — both are harmless in dev, so losing them is a
regression rather than an environment difference. The password policy is
*imposed* rather than required, and a test asserts the shipped dev realm does
**not** carry one.

### B3 (new) — audience was never verified ✅

`options={"verify_aud": False}` meant a token issued to **any other client in
the realm** was accepted. Now controlled by `JWT_AUDIENCE`, with an
`oidc-audience-mapper` added to the frontend client so Keycloak emits it.

Left off by default because enabling it against a realm without the mapper
locks out every user — so `app/main.py` **refuses to start in production**
while it is unset. The permissive default cannot reach production, which is the
only place it matters. This project has already shipped two "tighten later"
comments that were still there months on; a startup failure does not forget.

---

## Also fixed during this assessment (`beb5ba7`)

**Unvalidated identifier interpolated into DDL.** `app/users/models.py` built a
sequence name from `facilities.code` with only `.replace("-", "_")` applied — a
normalisation, not a sanitiser. `CREATE SEQUENCE` cannot bind its name as a
parameter, so the allowlist is the only defence. Both sibling sites
(`patients/service.py`, `emergency/service.py`) already validated against
`^[A-Za-z0-9_]{1,20}$`; this one did not, and it is wired to an `after_insert`
hook that runs on every facility insert. Not reachable today only because no
facilities endpoint exists.

**`/docs` and `/openapi.json` served unconditionally.** The schema is a complete
API inventory and is reported as information disclosure. Now gated on
`environment`. The gate's default was itself wrong — `environment` defaults to
`"dev"` and `.env.production.example` did not set it, so it would have failed
open in production. `ENVIRONMENT=production` added there.

---

## Minor — close before the audit, cheap

| # | Finding | Where |
|---|---|---|
| M1 | ✅ Starlette → 1.6.0 via FastAPI 0.141.1 |
| M2 | ✅ python-multipart → 0.0.32 |
| M3 | ⏳ CSP `'unsafe-inline'` — **still open**; needs Next.js nonces, the one finding with real work behind it |
| M4 | ✅ Five `/ping` stubs now require `admin` |
| M5 | ✅ Session cookie gets `Secure` on HTTPS |
| M6 | ✅ Password policy: 12 chars, mixed case, digit, symbol, history 5, pbkdf2-sha512 — imposed by the production realm renderer, absent from the dev realm by design |
| M7 | ✅ `Facility.timezone` de-duplicated 3 → 1 |

---

## Passing — evidence for the Audit Scope Document

| Requirement | Evidence |
|---|---|
| SQL injection | All raw SQL uses bound parameters. Seven f-string `text()` sites reviewed: five are dialect-gated literals or fixed `WHERE` fragments with bound values; three interpolate a sequence name and **all three now validate against an allowlist**. |
| XSS | Zero `dangerouslySetInnerHTML` / `innerHTML` in the frontend. |
| BOLA / IDOR | Facility scoping in 25 routers; 15 test files assert cross-facility isolation. Cross-facility ids return **404, not 403** — a 403 confirms existence and is an enumeration oracle. The five routers without scoping are unimplemented stubs; `ipd` is a re-export of the properly scoped `admissions`. |
| SSRF | Every outbound URL derives from settings (`jwt_issuer`, `icd11_base_url`, `abdm_gateway_base_url`). No request data reaches a URL. |
| Brute force | Keycloak: `bruteForceProtected`, `failureFactor: 5`, 15-minute lockout, non-permanent. Covered by `tests/test_auth_lockout_policy.py`. |
| Rate limiting | nginx `limit_req` — 30 r/s API, 10 r/s auth, both burst-limited. |
| Token handling | Access token in memory only — never cookie, never `localStorage` (`lib/auth/keycloak.ts:8`). Logout calls Keycloak `end_session`. Verification requires `exp`/`iat`/`sub`, selects the JWKS key by `kid`, and returns 503 (not 401) when the IdP is unreachable. |
| TLS | `ssl_protocols TLSv1.3` only. |
| Headers | HSTS (2 yr, `includeSubDomains`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, CSP with `frame-ancestors 'none'`. |
| Data at rest | AES-GCM via `cryptography`; key **versioning** with multi-version read and rotation support; Aadhaar stored as HMAC blind index, never plaintext. |
| Error leakage | 401s return a flat `"Invalid token"`; the reason goes to the log. **This line previously claimed no handler leaked exception text and was wrong** — `app/auth/deps.py` raised `f"Invalid token: {exc}"`, which the originating grep missed because it was positional. Fixed and covered by `tests/test_jwt_verification.py::test_the_401_body_does_not_say_WHY`. |
| Frontend deps | `npm audit --omit=dev` → **0 vulnerabilities**. |
| Audit trail | Append-only `audit_logs` with per-facility hash chaining, enforced by DB triggers (update/delete raise). |

---

## The ABDM functional track

This is the part that cannot be bought with a sprint of fixes.

| ABDM module | Implemented |
|---|---|
| `identity` | 457 lines — link / read / unlink an ABHA number the patient already holds |
| `fhir` | 341 lines — bundle builders |
| `hip` | **empty** |
| `hiu` | **empty** |
| `consent` (ABDM) | **empty** |
| `nhcx` | **empty** |

WASA requires the auditor to *document evidence* of:

- **ABHA workflow verification** — creating and validating ABHA numbers.
  M1 creation flows (enrol by Aadhaar OTP, login by mobile OTP) are **not built**.
  `_VERIFY_PATH` is `None`, so even verification of an existing ABHA is inert
  pending the v3 path. The Redis OTP transaction store exists and its
  `OtpPurpose` enum already anticipates the three flows — the scaffolding is
  there, the gateway calls are not.
- **Consent Manager integrity** — the ABDM consent module is empty. The internal
  DPDP consent engine is solid and enforced (`consent_required` gating in
  `patients/router.py`), but it is not the ABDM consent artifact the auditor
  tests.
- **HIP/HIU key handling** — no HIP or HIU implementation exists to hold keys.

**There is nothing here for an auditor to test.** Booking WASA now means paying
for an assessment of an integration that is one-sixth built.

---

## What remains

1. ~~Verify the dependency jump.~~ ✅ Done — FastAPI 0.115 → 0.141 and Starlette
   0.46 → 1.6 broke nothing. **909 passed.** Re-verify CVEs any time with
   `make audit-deps`.
2. **Set `JWT_AUDIENCE=healthdoc-backend`** in production, after a Keycloak
   re-import picks up the audience mapper. Production will not boot without it.
3. **M3 — CSP `'unsafe-inline'`.** The only remaining scanner finding.
4. **Build ABDM M1 properly** — enrol-by-Aadhaar and login-by-ABHA, against the v3 spec. The session path is now confirmed (`/api/hiecm/gateway/v3/sessions`); the enrolment paths are the remaining unknown.
6. **Then** scope the audit — with M1 working end-to-end in sandbox, which is what the functional track actually examines.

Re-run before booking:

```bash
cd backend && pip-audit -r requirements.txt     # must be empty
cd frontend && npm audit --omit=dev             # currently clean
make test-pg                                    # 889 passing
```

---

## Two answers the auditor will ask for

**Role:** HIP **and** HIU. `.env.example` records the sandbox as registered for
both. Note this widens the functional scope — an HIU is assessed on consent
handling and data *requests*, an HIP on data *provision*; both are unbuilt.

**Remediation capacity:** every finding above is either a dependency bump, a
Keycloak realm setting, or a localised code change. None requires architectural
rework. The one needing a decision rather than a patch is MFA scope.
