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
make test-pg                       # THE GATE — host venv, real Postgres, ~984
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

**Postgres `NULL <> NULL`, so `ON CONFLICT` does not fire on a nullable
column.** The seed's tariff uses `WHERE NOT EXISTS` for this reason.

**Migration-only constraints are untested by the SQLite fixture.** The shared
`db` fixture builds schema from ORM metadata, so triggers and CHECKs that exist
only in migrations are invisible to it. Use `make test-pg` for anything that
depends on them.

---

## Current state

- 984 tests passing; `pip-audit` and `npm audit` both clean.
- WASA cybersecurity track: blockers closed. One Medium open — CSP
  `'unsafe-inline'`, needs Next.js nonces in `src/proxy.ts`.
- WASA ABDM track: **not assessable**. `integrations/abdm/hip/`, `hiu/`,
  `consent/` and `nhcx/` are empty. M1 (ABHA enrolment and login) is built but
  its gateway paths are unconfirmed defaults — see below.
- See `docs/wasa-readiness.md` for the full assessment and
  `docs/manual-test-guide.md` for per-role testing.

### Known gaps, stated plainly

**ABDM M1 paths are unverified.** `abdm_path_enrol_*` and `abdm_path_login_*`
in `app/common/config.py` are the documented v3 shapes and have NOT been
confirmed against the sandbox. They are settings precisely so a wrong one is an
env change. `_VERIFY_PATH` in `identity/router.py` is deliberately `None`.

**Audit coverage is 8 of ~90 models.** `app.patients`, `app.consent` and
`app.files` have zero. `assert_audit_coverage()` exists to catch this and is
never called, with `AUDITABLE_MODULE_PREFIXES` empty. For DPDP this is a
data-access-logging exposure. Tracked as issue #290; needs an owner, not a
drive-by fix — each model needs a real decision about its facility/patient id
fields, and a wrong one fails at flush time.

**Two manual-test reports could not be reproduced** and were deliberately not
"fixed": `dev.emergency` 403 on `POST /patients` (that screen calls
`/emergency/patients`, which grants the role), and every API call firing twice
(likely React StrictMode in dev — confirm against a production build first).

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
