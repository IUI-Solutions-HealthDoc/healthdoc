# HealthDoc HMIS — working notes

Hospital management system for Indian facilities. FastAPI + PostgreSQL backend,
Next.js 16 + Electron frontend, Keycloak OIDC, all behind nginx in Docker
Compose. Targeting ABDM certification and a CERT-In WASA audit.

---

## Running it

```bash
make setup        # first run, or after pulling realm/seed/dependency changes
make up           # subsequent starts
make down
```

`make setup` MUST end with `Seeded development facility and 13 authenticated
users`. If it stops short, the accounts do not exist and every login fails —
which presents as a wrong password, so people blame themselves before the
script. It now verifies this and exits 1 naming the missing accounts.

App at https://localhost (self-signed cert). All thirteen dev accounts use
`devpass`; usernames and landing routes are in `docs/manual-test-guide.md`.

### Tests

```bash
make test-pg                       # THE GATE — host venv, real Postgres, ~1128
make test p=tests/foo.py k=name    # in-container, quick, skips DB tests
make contract                      # every frontend API call exists in OpenAPI
make audit-deps                    # pip-audit + npm audit, must be zero
make lint
```

`make test` and `make test-pg` are not interchangeable. The container run
cannot reach the published ports the host tests use, so DB tests skip there.
`make test-pg` is what CI approximates and what a green claim should mean.

---

## Conventions that are load-bearing

**404, never 403, for another facility's record.** A 403 confirms the row
exists and is an enumeration oracle. Tests assert this.

**Facility scope comes from `CurrentDbUser`, never the request body.**
`CurrentUser.sub` is the Keycloak subject and is NOT `users.id` — writing it to
a column that FKs to `users.id` has caused three separate defects.

**Money and quantities are decimal STRINGS on the wire.** Never `parseFloat`
one for display; a quantity that has been through a float cannot be reconciled
against the ledger.

**Mutations carry an `Idempotency-Key`.** Handlers 400 without it. A retried
GRN verification would post the same delivery to stock twice.

**Audit is opt-in per model** via `__audit_resource_type__` and
`__audit_facility_id_field__`. See the caveat below — coverage is thin.

---

## Traps this project has actually hit

Each of these cost real time. They are here so they cost it once.

**A fallback that guesses instead of abstaining.** This is the recurring one,
in five different disguises: the ABDM client secret sent as a Bearer token;
seven conftests defaulting `TEST_DATABASE_URL` to a hardcoded localhost; a bare
`except Exception` logging "proceeding offline" so a permanently broken
integration looked like a rural outage; `verify_aud: False` behind a "tighten
later" comment; `docs_url` gated on an `environment` that defaulted to `dev`.
When the honest answer is "I cannot do this here", say that — do not substitute
a plausible value.

**A control that dev cannot satisfy does not belong in the shared Keycloak
realm.** Forcing TOTP sends all thirteen dev identities to an OTP enrolment
screen; a strong password policy makes `kc set-password devpass` fail for all
thirteen. Both are correct for production and both live in
`scripts/deploy/render_keycloak_realm.py`, applied at render time.

**UI containment is not authorization.** Six endpoints returned 200 to a role
the frontend redirected away. A hidden menu stops a confused user and does
nothing about a token and curl. `tests/test_role_boundaries.py` guards this.

**When a bug report names an endpoint, the unit of repair is the route
family.** A report named one HOD route; five siblings had the same gap. Fixing
only what was reported passes the retest and fails the audit.

**Assert structure, not text.** Four assertions here failed because they
pattern-matched where a structural fact was available: a log message containing
the word it was asserted not to contain; a substring check satisfied by
`import pytest_asyncio`; a twelve-digit regex matching a UUID of repeated 1s. An
exact field set or a parsed AST is both simpler and stricter.

**`git fetch` fails but exits 0 in some sandboxes.** Always check ref dates
before claiming a branch is behind.

**A gate that passes vacuously is worse than no gate.** Three of these have now
been found, all reporting success while checking nothing. `make contract`'s
extractor used `\bapi(?:<[^;\n]*?>)?\(`, whose character class excluded every
generic containing a `;` or a newline — six real calls were invisible while it
printed "172 calls match". CI's `PR convention check` runs `pr_check.py` with
`working-directory: backend`, where every repo-root-relative path from
`git diff` fails an `exists()` test, so it prints "no python files to check"
and exits 0. And `assert_audit_coverage()` is never called at all. When a
check's output is a number, make something change that number and confirm the
number moves.

**A ✅ against a partial fix reads as a closed finding.** `wasa-readiness.md`
said "M4 ✅ Five `/ping` stubs now require `admin`". True — and twenty existed,
so fourteen stayed public for months because the tick told everyone to stop
looking. Say what was fixed AND what was left.

**Under the SQLite fixture, a row whose id came from the column's server
default cannot be updated afterwards.** `uuid_generate_v4()` is registered as a
Python function returning a STRING, so the row is stored under a string key
while the ORM holds a `UUID` and the later UPDATE matches zero rows —
`StaleDataError`. Postgres is unaffected. Assign the id explicitly when a
service inserts a row and then mutates it in the same flush.

**Editing a backend file can hang the dev container.** WatchFiles triggers a
reload, the reload waits on a background task that never drains, and the
backend stops serving while still reporting `Up`. It presents as nginx 502 or
a hanging request. `docker compose restart backend` recovers it; if uvicorn
then fails with `ModuleNotFoundError: No module named 'app'`, that is a mount
race on restart — `up -d --force-recreate backend` fixes it, and nginx needs a
restart afterwards to pick up the new container IP.

**Postgres `NULL <> NULL`, so `ON CONFLICT` does not fire on a nullable
column.** The seed's tariff uses `WHERE NOT EXISTS` for this reason.

**Migration-only constraints are untested by the SQLite fixture.** The shared
`db` fixture builds schema from ORM metadata, so triggers and CHECKs that exist
only in migrations are invisible to it. Use `make test-pg` for anything that
depends on them.

**Serving the app on a second address breaks it in three independent places,
each failing silently.** Reaching the stack over a LAN IP for a multi-PC demo
needed all three fixed; any one left undone looks like "login is broken".

1. *`NEXT_PUBLIC_*` pinned to an absolute host.* These are origin-relative by
   design (`API_BASE_URL` defaults to `/api/v1`). Setting them to
   `https://<ip>/...` makes the OTHER origin cross-origin, and CSP
   `default-src 'self'` then blocks the silent-SSO iframe. keycloak-js waits
   forever for a `postMessage` that can never arrive, so `init()` never
   settles, `isLoading` stays true, and the sign-in button sits disabled
   reading "Preparing sign-in…". Keep them relative — one build then serves
   localhost, a LAN address and a tunnel hostname alike.
2. *Next's dev server rejects non-localhost origins*, HMR websocket included.
   The dev runtime bootstraps through that socket, so the page never hydrates:
   server HTML renders, no effect ever runs, and every control is frozen in its
   initial state. Same visible symptom as (1), completely different cause. Fix
   is `allowedDevOrigins` in `next.config.mjs`, wired to `ALLOWED_DEV_ORIGINS`.
   Production builds have no HMR and no origin check.
3. *Keycloak derives `iss` from the Host header it was reached on.* The same
   realm mints `https://localhost/...` for a developer and `https://<ip>/...`
   for a ward PC, so a single pinned `JWT_ISSUER` 401s every call made from the
   other address — after a login that appeared to succeed. `JWT_ADDITIONAL_ISSUERS`
   takes an explicit comma-separated allowlist. This is safe because signatures
   verify against `JWT_JWKS_URL`, a fixed internal endpoint that does not depend
   on the token; it is an allowlist and there is no wildcard.

Debugging note: (1) and (2) present identically. What separates them is whether
React attached — check for a `__react*` key on a rendered button, and whether
the console shows `[HMR] connected`.

---

## Current state

- 1128 tests passing; `pip-audit` and `npm audit` both clean.
- WASA cybersecurity track: **all findings closed**, including M3 — the CSP now
  carries a per-request nonce from `frontend/src/proxy.ts` instead of
  `'unsafe-inline'`, and every route renders `force-dynamic` because a nonce
  cannot be baked into prerendered HTML.
- WASA ABDM track: M1 (ABHA identity), M2 (HIP) and M3 (HIU) are **built and
  tested** — 8 tables, ECDH/AES-GCM transfer crypto, fail-closed callback auth.
  `integrations/abdm/consent/` and `nhcx/` remain empty; the consent artefact
  handling lives in `hip/` and `hiu/`, and NHCX is out of scope for this audit.
- Frontend is production-ready: the `NEXT_PUBLIC_AUTH_MODE=dev` role picker is
  deleted, and `.env.production.example` carries the `NEXT_PUBLIC_*` build args
  the image needs.
- See `docs/wasa-readiness.md` for the full assessment,
  `docs/manual-test-guide.md` for per-role testing, and the Endpoint Atlas for
  every route with its access tier.

### Known gaps, stated plainly

**ABDM: the gateway now answers, and the path guesses were all wrong.**
Corrected on 2026-09-01 from the official v3 Postman collections ABDM support
supplied. Three things are now confirmed against the live sandbox rather than
documented-and-hoped:

- **The 403 was never a missing subscription.** `/gateway/v1/bridges/*` — the
  steps in NHA's onboarding email — answers 403 `900908` for a sandbox client
  because it is a retired API version, not because the client lacks an
  entitlement. The v3 equivalents (`/api/hiecm/gateway/v3/bridge-services`,
  `/bridge-service`, `/bridge/url`) answer **200 with the same credentials and
  the same headers**. A support ticket was raised on the wrong diagnosis; the
  reply "use the V3 Postman collection" was the whole answer.
- **ABDM segments v3 by capability, not by one base.** We assumed
  `/api/hiecm/v3/...` because sessions live under `/api/hiecm/gateway/v3/`.
  All ten M2/M3 paths built on that assumption returned 404. The real segments
  are `gateway`, `hip`, `user-initiated-linking`, `consent`, `data-flow` and
  `patient-share`. Each corrected path was verified by a non-destructive
  existence probe — GET it and read 404 as "no such route", anything else as
  "route exists": the POST-only paths answered 405, consent/request/init
  answered 400, and the bridge and certs routes answered 200 because GET is
  their real method. Every old path returned 404. Existence is all this proves;
  no payload has yet been accepted.
- **The bridge URL is self-service.** `PATCH /api/hiecm/gateway/v3/bridge/url`
  returns 202 and `SBXID_053401` now points at `https://abdm.healthdoc.world`.
  Asking NHA to register it was unnecessary.

`tests/integrations/test_abdm_gateway_paths.py` pins the shape so a revert to
either wrong form fails the suite — nothing in the suite noticed when all ten
paths were wrong, which is exactly how they stayed wrong.

The bridge is now fully provisioned: URL `https://abdm.healthdoc.world`, and
two services registered via `PUT /api/hiecm/gateway/v3/bridge-service` —
`SBXID_053401_HIP` and `SBXID_053401_HIU`, both active. `facilities.hfr_facility_id`
must equal the HIP service id or inbound callbacks 404 at `_facility_for_hfr_id`;
DEV001 is set to `SBXID_053401_HIP`.

**Callback signature verification is now unblocked and should be built.**
`GET /api/hiecm/gateway/v3/certs` returns a JWKS — two RSA keys, `use=sig`,
RS256 and RS512 — and `/.well-known/openid-configuration` points at it. The
shared secret was only ever a placeholder because the scheme "needs the sandbox
to confirm before it can be written without guessing"; the sandbox has now
confirmed it. This matters more than it looks: the bridge URL is live, so ABDM
can call us, and a shared secret ABDM does not know means every real callback
would be rejected. The secret is a stand-in for signature verification, not an
alternative to it.

**M1 ABHA verification is on.** `_VERIFY_PATH` is
`/v3/profile/login/search`, relative to `abdm_abha_base_url` — the ABHA host,
not the gateway, where the same path answers 503. Three details are not
guessable and each fails quietly if got wrong, so all three are pinned by tests:
the body key is `ABHANumber` (capitalised — `abhaNumber` returns 400 "Invalid
ABHA Number", which reads like bad input rather than a bad key); the value must
be hyphenated `91-0000-0000-0001` while we store it stripped; and an absent
ABHA is 404 `ABDM-1114`, a real answer that must not be logged as an outage.

Credentials must never be committed and CI must never hold them; the client
tests are fully mocked and stay that way.

**Audit coverage is 17 of 98 models**, up from 8. `assert_audit_coverage()`
still exists and is still never called, with `AUDITABLE_MODULE_PREFIXES` empty
— so the guard checks nothing. Patient creation is now audited explicitly on
both routes (`POST /patients` and `POST /emergency/patients`) rather than
through the listener, because `update_patient()` already writes its own row and
flipping the opt-in would double-write. Of the 12 models in `app.patients`,
`app.consent` and `app.files`, only three carry a `facility_id` column, and
`audit_logs.facility_id` is NOT NULL — so the other nine need a migration each
before they can opt in. Tracked as #290.

**`release-readiness` holds one unmerged commit** (`scripts/close_verified_issues.sh`).
Every other branch of ours is merged; the teammates' branches are not ours to judge.

---

## Working style that fits this codebase

Comments here explain **why**, especially where the obvious choice is wrong —
PKCS#1 v1.5 over OAEP because ABDM rejects OAEP, `python-jose` removed rather
than upgraded because one CVE has no fix. Keep that. A comment saying what the
line does is noise; one saying why it is not the other thing saves the next
person an hour.

Verify before claiming. Run the audit rather than reading the changelog; parse
the AST rather than grepping; check the ref date rather than trusting the fetch.
Several wrong conclusions here came from a check that confirmed an assumption
instead of testing it.
