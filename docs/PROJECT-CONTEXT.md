# Project context — HealthDoc HIMS

Orientation for anyone (human or AI agent) picking this repository up cold.

**This file is hand-written and authoritative for *why*.** It records the
decisions, conventions and traps that reading the code will not tell you —
usually because the code now looks obvious and the bug it prevents does not.

For *what* — the table list, the route list, the file map — do not read this
file. Regenerate the derived docs, which are read straight from the code and
are never stale by more than the last commit:

```bash
python3 ~/Desktop/Projects/project-intelligence/scripts/analyze-project.py \
    --project-dir . --output-dir .project-intelligence
```

That writes `.project-intelligence/AGENTS.md` plus `docs/architecture.md`,
`codebase-map.md`, `database.md`, `api.md`. It is **gitignored on purpose**:
two documents answering the same question, one generated and one authoritative,
drift apart and whichever a reader opens first looks definitive.

---

## What this is

A hospital management information system for small and mid-sized Indian
facilities. Not a CRUD app with a medical theme — the compliance surface drives
most of the design:

| Regime | What it forces |
|---|---|
| **ABDM V3** | ABHA identity, consent artefacts, FHIR R4 bundles, gateway callbacks |
| **DPDP Act 2023** | Consent lifecycle, erasure, data-principal access, breach notification |
| **NABH DHS 2nd Ed** | Clinical incident register, audit trail, break-glass with justification |
| **CERT-In** | 6-hour breach reporting clock |

Two consequences worth internalising before writing anything:

- **Almost nothing is deletable.** Audit logs, incidents, invoices, payments
  and clinical records are append-only or supersede-only. If a change would let
  a row disappear, it is probably wrong.
- **"Who did this, and when" is usually the requirement**, not metadata. A
  status field that records *that* something happened while losing *who* and
  *when* has failed at its actual job.

---

## Stack and shape

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16, Redis, MinIO, Keycloak OIDC
- **Frontend** — Next.js (App Router, `src/` layout), MUI, Electron shell
- **Entry point** — `backend/app/main.py`; modules are mounted from the `MODULES` list
- **Layering** — `router.py` (HTTP, roles, status codes) → `service.py` (rules, transactions) → `models.py` (ORM). Routers do not contain business rules; services do not raise `HTTPException`.

### As of 2026-08-20

| | |
|---|---|
| Migrations | 53, linear, head `0046`, downgrades present |
| Tables in spec | 96 (`spec_check.py`) |
| Tables with ORM models | 81 — **the 15-table gap is real, see Open hazards** |
| Backend tests | 550 collected |
| Backend modules | 30 under `backend/app/` |

Verify rather than trust these — they are a snapshot:

```bash
cd backend
python scripts/check_migration_integrity.py   # chain linear? head?
python scripts/spec_check.py                  # tables/enums vs schema doc
```

---

## Backend conventions that are not negotiable

Each of these exists because it was got wrong once and cost real time.

### 1. Business dates come from the facility's timezone

```sql
-- correct
(now() AT TIME ZONE facilities.timezone)::date
-- wrong, in every context
now()::date
CURRENT_DATE
```

`timestamptz::date` resolves against the **session `TimeZone` GUC**. Local dev
Postgres runs IST; CI and production run UTC. The same expression therefore
gives different answers on different machines, and the failure is invisible for
most of the day — it only appears for rows written between 18:30 and 00:00 IST.

A test that exercises this must parametrise over `SET LOCAL TimeZone` with both
`UTC` and `Asia/Kolkata`. A test that runs only under the local default will
pass with the bug reintroduced. This has already happened once.

### 2. Constraint names are passed bare

`backend/app/common/db.py` sets:

```python
NAMING_CONVENTION = {"ck": "ck_%(table_name)s_%(constraint_name)s", ...}
```

So write `CheckConstraint(..., name="status")`, not `name="ck_orders_status"` —
the convention prefixes it for you and a pre-prefixed name comes out as
`ck_orders_ck_orders_status`.

### 3. `xfail(strict=False)` is banned

It swallows *any* exception, including a fixture blowing up before the test
body runs. Four test files in this repo were found to have never executed once,
each hiding a real defect. If a test is expected to fail, `strict=True` and say
why; otherwise delete it.

### 4. `app/common/envelope.py` is raw ASGI, deliberately

It used to subclass `BaseHTTPMiddleware`, which never forwards
`http.disconnect` to the downstream app. SSE generators therefore never closed,
and every dropped queue-display client leaked a Redis subscription for the life
of the process. **Do not "simplify" it back to `BaseHTTPMiddleware`.**

All responses are `{success, data, error, meta}`. Only `application/json` is
buffered and rewrapped; everything else is forwarded chunk by chunk.

### 5. Redis pools are per event loop

`app/common/redis.py` keys its pool by the running loop. A single module-level
pool breaks the moment two event loops exist, which is normal under pytest.

### 6. New table with an FK to `patients.id`? Update the merge guard

A THID→UHID merge repoints every child row. Add the table to
`REPOINTED_ON_MERGE` in `app/patients/service.py`, or
`test_repointing_covers_every_patient_fk` fails — by design. Skipping it strands
a patient's records on the merged-away identity while the surviving chart looks
complete. `scripts/maintenance/add_merge_repoint.py` does the edit.

### 7. Import failures must be loud

`main.py::_include` re-raises anything that is not the module's own absence. A
bare `except ModuleNotFoundError` once removed an entire module from the API
because a dependency was missing, and nothing failed.

### 8. Smaller sharp edges

- `sa.table()` projections only know the columns you name — writing to an
  unlisted one is a compile-time "Unconsumed column names" error.
- asyncpg rejects a `str` for a `timestamptz` bind even with an explicit
  `CAST`. Pass a real aware `datetime`.
- SQLAlchemy 2.0 `Mapped[...] = mapped_column(...)` is `ast.AnnAssign`, not
  `ast.Assign` — matters when writing tooling that parses models.
- `audit_logs` is append-only, and its `ip_address` is `INET`: validate before
  writing or a bad host raises *inside the caller's transaction* and takes an
  unrelated write down with it.

---

## Testing

There are two suites and they are not interchangeable.

```bash
make test                    # SQLite — fast, misses constraints and concurrency
make test-pg                 # real PostgreSQL — the one that counts
make test-pg k=late_utc      # filter by -k
make test-pg p=tests/nursing # filter by path
make test-db-reset           # REQUIRED after editing an existing migration
```

Local Postgres is on port **55432**, not 5432. `.env` holds container-internal
hostnames (`redis:6379`, `minio:9000`) which do not resolve from the host — the
Makefile rewrites them for the test environment.

SQLite cannot see: partial unique indexes, `INET`/`JSONB` behaviour, `sqlstate`
on `IntegrityError`, real concurrency, or timezone-dependent date arithmetic. A
constraint test that passes only on SQLite has proved nothing.

### `make test-pg` does not make the `db` fixture PostgreSQL

This catches people. The shared `db` fixture in `tests/conftest.py` is **always**
in-memory SQLite. `make test-pg` only puts a real `DATABASE_URL` where tests can
find it — a test that needs Postgres has to open its own engine, the way
`tests/test_admissions_concurrency.py` and `tests/opd/test_visit_facility_scope.py`
do.

A test that skips itself on `db.bind.dialect.name != "postgresql"` therefore
skips **everywhere**, in both suites, forever — while the run still reports a
tidy `skipped` and the file looks like coverage. That is worse than not writing
it.

### Watch a new test fail, and read *why* it failed

Reverting the fix and confirming the test goes red is not enough. Three separate
times in this repo a guard went red for the wrong reason:

- the `#387` boundary test passed with the fix reverted, because local Postgres
  runs IST and the bug only appears under UTC;
- a `-s ours` merge reported clean while silently dropping a fix;
- `test_visit_facility_scope` first failed on a duplicate `visit_number` — the
  residue of the previous passing run — rather than on the behaviour under test,
  because the facility code was hardcoded instead of generated per run.

In each case the signal said "working" while the mechanism underneath was wrong.
Read the assertion message, not the colour.

---

## Frontend conventions

### The API client is `src/lib/api.ts`

Typed against the envelope, adds `Idempotency-Key` on POST and `If-Match` for
`row_version`, and surfaces `409 module_disabled` and `409 stale_write` as typed
properties on `ApiError` rather than generic failures.

**The access token is held in memory only.** Never `localStorage`, never
`sessionStorage`, never a cookie. A stolen clinician token is full
patient-record access. Re-obtained from Keycloak by silent SSO on reload.

### Roles must match the Keycloak realm verbatim

There are **13** realm roles: `receptionist doctor nurse lab_tech
radiology_tech pharmacist emergency supervisor admin hod auditor patient
superadmin`.

`src/config/roles.ts` carries a compile-time guard against `RealmRole`, so the
two lists cannot drift silently. This matters more than it looks: a mapping
that used `lab_technician` (not a realm role) fell through to a
receptionist default, so lab techs, auditors, HODs and radiology techs all
signed in successfully and landed in the registration desk — a screen they
cannot use, whose API calls 403 for reasons it cannot explain. An unrecognised
role now maps to `null`, and `AuthUser.role` is `Role | null` so screens are
forced to handle it.

### Other things that will bite

- **Imports are case-sensitive in CI.** `@/components/ui/button` resolves on
  macOS and fails on Linux. The file is `Button.tsx`.
- **`public/silent-check-sso.html` must exist.** Without it Keycloak's
  `check-sso` iframe 404s and a signed-in user is treated as logged out on
  every page load.
- **Route groups add no path segment.** `(auth)/login` and `login` both resolve
  to `/login` and Next fails the build.
- Every route in `getDefaultRouteForRole` must exist under `src/app`. It is a
  total `Record<Role, string>` so a new role cannot be added without deciding
  where that person lands.

---

## Where things stand

**Backend: complete.** Every issue blocking a frontend screen is closed.
What remains is QA (#240–#242), infra (#244, #250), docs (#249), the remaining
integration journeys (#243) and a DPDP design call (#368) — none of which block
anyone.

**Frontend: the real work.** `staging` has a good shared UI layer, the API
client, and genuine feature code for **doctor, billing, admin, audit-viewer,
reports, consent**. It has one-file stubs for **nurse, pharmacy, lab,
radiology, inventory, receptionist, queue-display, ipd, emergency,
patient-portal** — those live on contributor branches and are being ported one
area at a time.

Branch strategy: `aditya-choudhary` was level with `staging` and is the base.
`ishika`, `Vanshika` and `ankit` are ~235 commits behind, so their work is
**ported** (checked out by directory onto a fresh branch) rather than rebased —
replaying 40 commits across that much drift costs days for the same result.
Porting is also where each screen gets moved onto the canonical API client.

---

## Open hazards

Recorded because none of them will announce themselves.

1. **15 tables exist in migrations with no ORM model.** `spec_check` counts 96,
   the model scan finds 81. Those tables cannot be read through the ORM and
   nothing type-checks against them.
2. **Notification preferences are not consulted on the publish path.**
   `notification_preferences` (0044) is honoured when reading history, but
   `publish_event()` and the SSE fan-out ignore it — silence a role and the
   live event still arrives. The setting appears to work and does not.
3. **Almost nothing in the frontend calls the API.** At the last count 4 files
   in the whole tree touched the client. Merging the remaining branches yields
   screens that render fixtures; the wiring is separate, larger work.
4. **`scripts/pr_check.py` has known rule gaps**, each with a real example from
   review — not yet filed.

---

## Working agreements

- **Deadline mode.** Mechanical fixes get carried by whoever finds them.
  Reviews go back to the author only when the fix needs a decision they own.
- **Explain the "why" in the commit and the code comment,** not the "what". The
  diff already says what changed. Every convention above exists because someone
  had to rediscover a reason that was never written down.
- **Never assert a test guards a fix without watching it fail.**
- **`git branch --merged` does not see squash merges.** Derive "safe to delete"
  from PR state (`gh pr list --state all`), never from git ancestry — and apply
  the protected-branch filter to the *final* list, not to its inputs.
- **Secrets** (ABDM sandbox credentials in particular) live in a gitignored
  `.env` locally and GitHub Actions secrets for deploy. CI never holds them:
  the ABDM client tests are fully mocked and must stay that way.
