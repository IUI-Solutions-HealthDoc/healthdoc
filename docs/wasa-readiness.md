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
| Cybersecurity (VAPT) | ✅ blockers closed · **all minors closed** · **1049 tests pass on the upgraded stack** |
| ABDM functional | ⚠️ **Partially assessable** — M1/M2/M3 built and tested; no sandbox round trip yet |

> **A naming collision, because it has already caused confusion.** M1/M2/M3 in
> the *Minor findings* table below are VAPT scanner findings (Starlette,
> python-multipart, CSP) and are all closed. M1/M2/M3 in the *ABDM* section are
> integration milestones (ABHA identity, HIP, HIU). They are unrelated. When
> someone asks "is M3 done", ask which M3 they mean.

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
| M3 | ✅ CSP `'unsafe-inline'` removed — per-request nonce in `frontend/src/proxy.ts`, CSP moved off nginx. Needed `force-dynamic` in the root layout: every route prerendered as static, and a nonce cannot be baked into static HTML, so without it the policy blocked Next's own inline bootstrap and every screen rendered blank. Verified in a browser across 7 screens and all 13 roles — zero violations |
| M4 | ✅ **All twenty** `/ping` stubs require `admin`. This line previously read "Five `/ping` stubs now require `admin`" — true, and incomplete: twenty existed, so fourteen stayed public and the ✅ told everyone the finding was closed. Unauthenticated routes are now 8, all deliberate: OpenAPI docs (off outside dev), health, metrics, and the waiting-room queue display. Guarded by `test_role_boundaries.py` |
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
| Access tiers | Of 266 mounted routes: **247 role-gated**, 11 authenticated without a role restriction, **8 unauthenticated** — the OpenAPI docs (disabled outside dev by `ENVIRONMENT`), health, metrics and the queue display, which is public by design. Counted from FastAPI's resolved dependency tree, so router-level and parameter-level `require_roles` both register. |
| Frontend auth | The `NEXT_PUBLIC_AUTH_MODE=dev` role picker — a second sign-in path that fabricated a user and entered any role workspace without a bearer token — is deleted, not merely disabled. |
| Contract gate | `make contract` verifies every frontend API call against the OpenAPI schema. Its extractor was blind to any call whose generic type argument contained a `;` or newline (six real calls); fixed, now 179 checked. |
| Audit trail | Append-only `audit_logs` with per-facility hash chaining, enforced by DB triggers (update/delete raise). |

---

## The ABDM functional track

Previously this section said "there is nothing here for an auditor to test."
That is no longer true, and the sentence stayed accurate for longer than the
code did — hence the dates on every claim below.

| ABDM module | State |
|---|---|
| `identity` (M1) | ✅ Built — ABHA link/read/unlink, **plus** enrol-by-Aadhaar-OTP and login-by-mobile-OTP. 46 tests |
| `fhir` | ✅ Bundle builders |
| `hip` (M2) | ✅ Built — care contexts, links, consent notification, health-information request gate. 13 tests on the gate alone |
| `hiu` (M3) | ✅ Built — consent requests, artefacts, data requests, encrypted receipt. 14 tests |
| `hi_crypto` | ✅ X25519 + HKDF-SHA256 + AES-256-GCM transfer crypto. 11 tests |
| `callback_auth` | ✅ Inbound gateway authentication, fails closed. 7 tests |
| `consent` (ABDM) | **empty** — the artefact handling lives in `hip/` and `hiu/`; this package is unused |
| `nhcx` | **empty** — claims/insurance, out of scope for this audit |

### What an auditor can now examine

- **ABHA workflow verification** — M1 enrol and login flows exist and are
  tested: the Aadhaar number is RSA-encrypted before transmission, never
  logged, and the endpoints refuse rather than send plaintext when the public
  certificate is absent.
- **Consent Manager integrity** — `hip/service.py::authorise_hi_request` is the
  single gate through which records leave. It refuses on: an artefact we do not
  hold, a revoked artefact (indistinguishably from an absent one, so artefact
  ids cannot be enumerated), an expired artefact, an HI type outside the grant,
  and a period outside the granted window (refused, **not silently clipped**).
  Release additionally requires a *confirmed link*, not the artefact alone.
- **HIP/HIU key handling** — `hi_crypto.py`. Ephemeral X25519 per bundle;
  HKDF over the raw ECDH output rather than using the curve point as a key; IV
  derived from **both** nonces so neither party alone fixes it; AES-GCM so
  tampering fails to open rather than decrypting to plausible clinical data.
  The HIP keypair never leaves the call stack. The HIU must persist its private
  key — the exchange is asynchronous — so it is stored AES-GCM-encrypted, bound
  by associated-data to the one request row entitled to it, given an expiry,
  and cleared on completion or revocation. It is excluded from `audit_logs`,
  because that table is append-only and would otherwise keep a copy after the
  row was cleared.

### What is still NOT proven, and must not be claimed

**No call has ever been made to the ABDM sandbox.** Every test above is
self-consistency between our own two halves — our HIP encrypts, our HIU
decrypts. That proves the implementation is coherent; it does **not** prove
ABDM agrees, and this document must not be read as saying it does.

Specifically unverified:

- All eleven gateway paths in `app/common/config.py` (`abdm_path_hip_*`,
  `abdm_path_hiu_*`, and the four M1 paths). They are the documented v3 shapes.
  They are settings, so a wrong one is an env change rather than a release.
- `_VERIFY_PATH` in `identity/router.py` is still deliberately `None`.
- The callback authentication is a **shared secret**, not ABDM's signature
  scheme. That is the weakest acceptable answer and it is there because the
  strong answer needs the sandbox to confirm the signing scheme before it can
  be written without guessing. `verify_callback` is the one function that
  changes when it is known.
- Whether ABDM sends the ECDH public key raw or with an uncompressed-point
  prefix. Both are accepted; anything else is refused.

### What is needed to close it

Sandbox credentials on a machine that is not CI: `ABDM_CLIENT_ID`,
`ABDM_CLIENT_SECRET`, `ABDM_HFR_FACILITY_ID`, `ABDM_PUBLIC_KEY_PEM`,
`ABDM_CALLBACK_SHARED_SECRET`. All are `change-me` or absent today, which is
why the endpoints answer 503 with a reason rather than failing obscurely. They
must never be committed, and CI must never hold them — the client tests are
fully mocked and are to stay that way.

---

## What remains

1. ~~Verify the dependency jump.~~ ✅ FastAPI 0.115 → 0.141, Starlette 0.46 →
   1.6. Re-verify CVEs with `make audit-deps`.
2. **Set `JWT_AUDIENCE=healthdoc-backend`** in production, after a Keycloak
   re-import picks up the audience mapper. Production will not boot without it.
3. ~~M3 — CSP `'unsafe-inline'`.~~ ✅ Closed.
4. ~~Build ABDM M1.~~ ✅ Built. ~~Build M2/M3.~~ ✅ Built.
5. **Run all three against the sandbox.** This is now the only thing between
   this document and an assessable integration. Until it happens, every ABDM
   claim here is "implemented and self-consistent", never "verified".
6. **Then** scope the audit.

Re-run before booking:

```bash
make setup                                      # must end with the 13-user banner
make test-pg                                    # 1049 passing
make audit-deps                                 # both ecosystems zero
cd frontend && npm run test:e2e                 # 9 roles, WCAG + silent SSO
```

> **Keeping this file honest.** Every number above was produced by running the
> command beside it on 29 Aug 2026, not carried forward. The previous version
> quoted three different test counts (930, 909, 889) in three places, all stale,
> which is how a readiness document stops being evidence and becomes decoration.
> If you change this file, re-run the commands.

---

## Two answers the auditor will ask for

**Role:** HIP **and** HIU. `.env.example` records the sandbox as registered for
both. That widens the functional scope — an HIU is assessed on consent handling
and data *requests*, an HIP on data *provision* — and both are now built and
tested, though neither has spoken to the sandbox.

**Remediation capacity:** every finding above is either a dependency bump, a
Keycloak realm setting, or a localised code change. None requires architectural
rework. The one needing a decision rather than a patch is MFA scope.
