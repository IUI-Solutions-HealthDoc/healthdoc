# Tariff write safety — 9 September 2026

## Publication and scope

Tariff UI commit **`22bfd62`** is published in
[PR #545 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/545).
It builds on merged invoice-safety PR #543. The server follow-up described here
is carried separately on **`fix/tariff-write-safety`**, based on `22bfd62`;
it was not included in PR #545. No main PR, merge or production deployment was
performed by this work.

PR #545's first backend job failed **before dependency installation or tests**:
the runner's Chrome apt repository returned a package-index hash mismatch while
installing the PostgreSQL client. The failed backend job was rerun unchanged;
no integrity checks were disabled. The original frontend and browser jobs
passed, including the tariff-maintenance step. The backend rerun also passed:
run `34386014028`, attempt 2, job `102592635314`. On the 10 September IST
initial recheck, PR #545 remained approved with all four active checks green at head
`cd1cc8b`. That head adds a staging-sync merge to `22bfd62` with an identical
file tree. PR #545 was subsequently merged into staging at `43195e1` at
18:45:39 UTC on 9 September (00:15:39 IST on 10 September). The local follow-up
was still local at that recheck. It is now being submitted separately to staging;
the verification below does not claim it has been merged or deployed.

## PR #544 CI recheck — 10 September IST

The separate `staging` → `main` promotion PR #544 at staging head `2fb9106`
had two failed backend jobs (push and pull-request events). Both logs showed
the same Chrome package-index **Hash Sum mismatch** during PostgreSQL client
installation, before application tests. Only those failed jobs were rerun;
no source changes, checksum bypass, skipped tests or empty commit was needed.

- Pull-request run `34385099853`, attempt 2, backend job `102597281582`:
  **1,507 passed, four existing warnings**, 181.95 seconds.
- Staging push run `34385060287`, attempt 2, backend job `102597287788`:
  **1,507 passed, four existing warnings**, 158.10 seconds.
- Frontend and nurse-auth-e2e passed in both runs; the pull-request release
  policy passed. The scheduled Electron job was skipped, not tested.

GitHub reported PR #544 **merged by `kandol007`** at `8b75598` at 18:45:27 UTC
on 9 September (00:15:27 IST on 10 September), during final verification.
This session reran CI but did not issue a merge command. Its 1,507-test count
is for the published staging code, not the uncommitted 31-test tariff-safety
follow-up. PR #545 merged to staging twelve seconds later, so its tariff UI
was not included in #544's main promotion.

## Defects reproduced before fixing

Four initial real-PostgreSQL tests failed on the original code:

1. Tariff creation accepted a missing `Idempotency-Key` (201 instead of 400).
2. Replaying a successful create returned an overlap error instead of its
   original tariff.
3. Replaying retirement returned 404 instead of the original 204.
4. A second concurrent first-version write bypassed serialization. The legacy
   unique constraint does not protect a general tariff with a NULL scheme.

The follow-up also exposed a 204 response-body issue at the ASGI boundary:
the JSON envelope middleware attached a representation to retirement. This
route now explicitly uses an empty `Response`, with tests requiring zero bytes.

## Implemented

- Both tariff mutations require a nonblank action key of at most 255 characters.
  Keys are scoped by authenticated database actor and endpoint. The request
  fingerprint includes facility and target/body: moving an account cannot replay
  its former facility's response, and reusing a key with different data is 409.
- Acquire a transaction-level PostgreSQL advisory lock for the actor/action
  before reading or reserving the existing idempotency table. Reservation,
  tariff writes and saved response commit or roll back together. An incomplete
  committed reservation fails closed; it does not rerun a possibly completed
  mutation. No new table or migration was introduced.
- Acquire a separate transaction-level lock for **facility/code/scheme** in
  both creation and retirement. This protects even the first version when no
  row exists yet and serializes different actors/keys writing the same family.
  Lock order is action then family. Locks release on commit, rollback or lost
  database connection; no process-local mutex is used.
- Preserve original prices and invoice references. New dates must follow the
  latest version, including retired history. Ambiguous pre-existing open or
  overlapping ranges are refused for review, not silently repaired. Retirement
  checks ownership before replay and never deletes history.
- Creation now uses `CurrentDbUser` for active-actor and facility enforcement.
  Billing/admin remain the only writers. Other-facility retirement remains 404.
- Validate nonblank codes/descriptions, control characters and Numeric(12,2)
  limits before database writes. Blank scheme input normalizes to general/NULL.
- Browser forms retain conservative read-back after an ambiguous error. No
  automatic retry or new pricing policy was added. The API key is now enforced
  and replayable, not merely a frontend header.

The API Endpoint Builder skill guided checks of validation, authorization,
failure handling and route-level regression coverage; existing HealthDoc
transaction, envelope and idempotency conventions remain authoritative.

## Fresh evidence

The focused PostgreSQL safety suite was rerun on 10 September IST while
investigating PR #544's unrelated CI setup failure: **31 passed in 1.82s**.
The broader gate and browser evidence below are from the preceding completed
verification, not a fresh whole-project/browser sweep on this recheck.

| Check | Result |
|---|---|
| New tariff safety suite | **31 passed** on migrated PostgreSQL, not SQLite mocks |
| Complete billing suite | **109 passed** |
| Full backend gate | **1,538 passed**, four existing ABDM Pydantic alias warnings |
| Script tests | **14 passed** |
| Migration integrity | 75 migrations, linear chain, test DB head 0068 |
| Frontend tests | **62 passed**, typecheck and scoped ESLint passed |
| Contract gate | **207 API calls** match OpenAPI; matrix regenerated |
| Explicit PR convention scan | Four changed backend application files; zero blockers/warnings |
| Browser tariff workflow | **10/10 passed** with real Keycloak and local backend |

Concurrency tests hold one transaction open, observe the contender's ungranted
lock in `pg_locks`, then release and assert persisted results. They cover first
general-version collision, next-day revisions, same-request replay, and
retirement versus revision. They do not merely launch two tasks and assume
those tasks overlapped. Rollback tests inject response-record failure and verify
both tariff changes and the action reservation disappear before a successful
retry. Further tests cover different bodies/targets, different actors, moved
facility, forbidden roles, malformed input and incomplete reservations.

The browser suite creates only a unique synthetic tariff family. It proves
create/revision, zero-priced scheme, conflict, retirement/history, independent
admin retirement and receptionist denials. It now replays the browser's exact
create and retirement requests with their original keys and checks no additional
row is created. These replay probes use authenticated browser fetch after the
UI write; they are not a claim of a new automatic-retry button. The catalogue
503 is the sole injected transport failure. Evidence:
`docs/evidence/tariff-write-safety-20260909/tariff-management.json` and ten
screenshots. Request tokens and action keys are not written to that evidence.

Ruff passes on the new helper/tests and changed schemas/service. The legacy
billing router still reports existing FastAPI dependency-default B008 findings;
its imports were sorted. This is not a whole-backend lint-clean claim. The
default PR scanner ignores uncommitted files, so the explicit four-file scan,
not “no python files to check”, is the relevant verification.

## Deployment and remaining work

- No application database migration or seed reset was run. The application
  remains at **0067**; only the isolated test DB is at 0068. Browser revision
  dates are two days apart. The next-day one-day-version case passes in the
  migrated test DB; reviewed 0068 deployment is still required for that case.
- Update any direct tariff API clients to supply stable action keys on **both**
  write endpoints. The tariff UI already supplies them. Missing keys now fail
  instead of performing a write. After an ambiguous outcome, retain the same
  key and body; changing them is a new operation, not a replay.
- All production tariff writers must use this service/lock protocol. Direct
  SQL, old application replicas and unreviewed seed/import scripts do not
  acquire advisory locks. This change does not retrofit a database-wide
  exclusion constraint or clean up existing corrupt tariff history.
- PostgreSQL READ COMMITTED transactions are the tested runtime. Long-running
  lock holders, lock-timeout UX and broader operational contention remain
  deployment/load acceptance work, not proved by a two-writer regression.
- Prices/schemes/dates still require finance approval. The UI and safer writes
  do not supply a hospital fee schedule. No posted invoice was repriced and no
  payment/refund idempotency implementation was changed in this follow-up.
- No live ABDM worker, OTP, consent or data exchange was initiated. M1–M3
  readiness remains governed by the separate current gap-analysis report.

Next bounded feature is **F04: external-referral result intake/read-back UI**
using the existing order APIs. eMAR recording still needs agreed clinical
dose-identity and concurrent-administration rules. Publish/review this backend
follow-up before calling tariff write safety deployed.

## Reproduce

```bash
make test-pg p=tests/billing/test_tariff_write_safety.py
make test-pg
make contract
cd frontend
npm test
npm run typecheck
E2E_BASE_URL=https://localhost E2E_ALLOW_MUTATIONS=1 \
  E2E_RUN_ID=tariff-safety-your-new-id \
  E2E_EVIDENCE_DIR=../docs/evidence/tariff-safety-your-new-id \
  npm run test:tariff-management
```

Use a fresh evidence directory and a local synthetic-data stack. Run the full
backend gate before browser tests to avoid known runtime contention. Synthetic
committed test rows remain in the named test DB; synthetic browser rows remain
in the local application DB. No real hospital tariff is altered by the harness.
