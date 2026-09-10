# External-referral results — implementation progress, 10 September 2026

## Publication and scope

The preceding tariff-safety work was committed and published in
[PR #547 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/547),
with all four active CI checks passing. GitHub reported it merged during this
session; this session did not issue the merge command.

The referral work is on **`feat/external-referral-results`**, originally branched
from staging `43195e1` before #547 merged. On 10 September the user requested
commit/publication and a live local browser retest. Implementation `45fa36d`
and staging integration `ae824a9` were pushed in
[PR #549 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/549).
The PR was created as draft with the runtime blocker disclosed; it was later
marked ready and merged outside this session as staging `ea909f9`. All four
active CI checks passed on `ae824a9` (Electron packaging skipped), but that
merge did **not** contain the subsequent input fix or project status document.
Those follow up on **`fix/external-result-input`**. No merge command was issued
by this session. This is **partial F04**, not closure of all referrals.

## Implemented

- Order responses expose `fulfilment_mode` and `completed_at`. Old idempotency
  snapshots can report a null mode; the ordering client re-reads the actual
  order before deciding whether to call a department. Unknown is not internal.
- Externally referred lab/radiology headers no longer trigger a local department
  detail call that cannot be fulfilled. No local accession or performed test is
  claimed. Existing internal ordering retains its clinical detail request.
- The doctor orders panel offers a **Referred externally** filter and a
  per-order **Outside results** panel. Patient name/UHID and order number stay
  visible while recording optional provider/date and a required summary.
- Client validation rejects blank/oversized summaries, oversized provider names,
  malformed/future dates and missing patient/order confirmation. Dates remain
  calendar strings, not converted timestamp values.
- Save through the existing external-results API; show the resulting receipt,
  refresh order status/history, and retain the receipt if read-back fails.
  Earlier result entries are unchanged; a correction is a deliberate new entry.
- Ambiguous server/network outcomes freeze the original payload and key for an
  exact retry. Confirmed success prevents accidental resubmission. The key stays
  in memory only: navigating away/reloading requires checking history before
  entering the result again. No persistent replay outbox was added.
- Patient/encounter/order-keyed boundaries clear drafts and receipts before
  paint and suppress late results and save callbacks after switching away.
  Order/history failures remain errors rather than successful empty lists.
- Completed encounters shown in the workspace keep new orders locked but allow
  results for existing referrals. Cancelled orders expose read-only history.
- Backend external-result replay rechecks current order/facility ownership
  **before** consulting the saved response. An account moved between facilities
  can no longer replay its previous facility's report. Missing/cross-facility
  orders remain 404. Action keys are required, nonblank and at most 255 chars.
- **Results review → External referrals** now provides an inbox across visits,
  independent of the current OPD token. It includes closed encounters/visits,
  pending/completed/cancelled/all filters, pagination, patient UHID/THID, visit
  number, result counts and last receipt time. Its new endpoint is
  `GET /orders/external-referrals?state=pending&limit=25&offset=0` (limit 1–100).
  Doctors see orders they created; admins can use the API for their facility.
  The existing admin frontend boundary is unchanged: no admin or nurse menu
  was added. Inconsistent patient/visit/facility joins are omitted, not exposed.
- Inbox page/filter/patient changes discard old details before replacement
  reads. Failed reads remain errors. A result receipt stays visible if its
  completed order leaves the pending list after a save.
- **Report attachments:** optional PDF/PNG/JPEG selection and explicit upload
  via `/files/upload`, linked as `result_file_id` when recording the result.
  The shared API client now preserves bearer auth without forcing JSON headers
  onto multipart uploads. Client checks reject empty/over-25-MB/disallowed
  selections; backend magic-byte validation remains authoritative.
- Uploaded files remain selected through result-write failures. Exact result
  retries keep the file ID as well as the original text/key. Removing a file
  selection does **not** erase it. Unknown upload outcomes block re-upload and
  result submission pending reconciliation: the existing upload endpoint has
  **no idempotency or automatic recovery protocol**.
- Existing attachments offer explicit metadata-authorized temporary downloads.
  Patient/file identity and erasure are checked before requesting a signed URL;
  switched-patient responses, unsafe URL schemes and expired-link navigation
  are rejected. No presigned links, file contents or patient drafts are persisted
  in browser storage or test evidence by these controls.
- **Public file signing:** the storage client previously signed for the internal
  `minio:9000` HTTP address in production. A separate HTTPS signing client now
  uses `MINIO_PUBLIC_ENDPOINT` and `MINIO_REGION`, while uploads stay internal.
  Missing/invalid production download configuration returns 503 rather than
  presenting an internal link as usable. Development retains direct-storage
  fallback. The hostname/certificate/proxy still need deployment provisioning;
  no local secrets, running service or public DNS configuration was changed.

No database migration, department capability change, clinical result
verification, FHIR publication, live ABDM exchange or production operation was
performed. No role was granted additional backend permission. The API Endpoint
Builder skill guided the input, ownership, replay and failure-path checks.

## Verification and limits

### Runtime fix after #549 merged — current evidence

The result-entry failure is now fixed in the scoped form. A burst of 128 input
events reproduced `Maximum update depth exceeded` before the fix, removing the
timing dependence that let some ordinary typing runs pass. Diagnostics found
pending MUI `FormControl` updates. Changing to uncontrolled `TextField` inputs
also failed, this time directly in `FormControl.onFilled`; that attempted change
was replaced, not shipped.

The final form retains **controlled values** and the same MUI outline components,
with explicit labels/helper IDs rather than `TextField`'s implicit `FormControl`.
This removes the redundant filled-state update path without a framework upgrade,
vendor patch, slower typing, suppressed errors or altered clinical permissions.
Patient/order keys, validation and frozen retry payloads remain unchanged.

- Strengthened rendered-browser gate: **9/9 passed twice**, no page errors.
  Includes the formerly failing burst, original short `Locator.fill`, long
  zero-delay multiline keystrokes, exact displayed/submitted text, ambiguous
  response retry, receipt preservation and fresh empty correction inputs.
- Frontend tests: **83 passed**, typecheck, scoped ESLint and a fresh production
  build passed.
- The browser regression is now an explicit step in the existing
  `nurse-auth-e2e` CI job; no second infrastructure stack or skip was introduced.
- Passing evidence: `docs/evidence/pr549-input-outlined-after-20260910/` and
  `docs/evidence/pr549-input-outlined-repeat-20260910/`. Failing baseline:
  `docs/evidence/pr549-input-burst-before-20260910/`. Temporary component-lane
  diagnostic instrumentation was removed. Screenshots were visually inspected.
- The final label-position adjustment was followed by another **9/9 pass** in
  `docs/evidence/external-result-input-final-20260910/`; its screenshot confirms
  the labels align with their outlines and errors remain adjacent to the field.

These tests render real local MUI/Next.js and authenticate through Keycloak but
simulate clinical responses. **Populated inbox, actual PostgreSQL/MinIO upload,
attachment download and clinical sign-off acceptance remain separate work.**
This is a local input fix, not evidence that every other MUI form has been
stress-tested or that the entire referral journey is production-ready.

### Publication retest — integrated with staging

Historical evidence before the scoped input fix above:

- `make test-pg`: **1,573 backend tests and 14 script tests passed**; migration
  checker reports 75 linear migrations through `0068`, downgrades present.
  This gate uses the disposable test database, not a production upgrade.
- Frontend suite: **82 passed**, typecheck passed before the staging integration;
  GitHub frontend CI subsequently passed on the integrated commit.
- All-role real-Keycloak dashboard sweep: **50/51 screens passed**. Admin
  `/admin/data-protection` timed out waiting for `#main-content`; every other
  captured screen completed with no failed API responses. The admin-only retry
  **passed 12/12**, including data protection (8 successful API responses).
  This is separate evidence, not a substitute for the failed first run; the
  intermittent navigation/server cause is not established.
- Visible Chrome: actual doctor login, results list and the new external-referral
  inbox opened. Results initially returned a local nginx 502, then loaded on
  reload. The pending inbox contained zero records; this does not prove a
  populated inbox, writes, attachments or pagination.
- Referral fault-scenario browser repeat: **failed overall**, despite seven
  successful assertions. The error occurs while filling the result summary:
  `ExternalResultPanel`'s `onChange` → MUI `InputBase`/`TextareaAutosize` → React
  `Maximum update depth exceeded`. No verified root cause or fix yet.
- Local evidence directories: `docs/evidence/pr549-live-dashboards-20260910/`
  `docs/evidence/pr549-admin-retry-20260910/`, and
  `docs/evidence/external-results-pr549-retest-20260910/`. Generated browser
  artifacts remain local and ignored, not committed or posted to GitHub.

The acceptance-orchestrator workflow kept publication separate from acceptance:
the failures were posted on #549 and not waived because CI was green. No full
production frontend build, real storage download or clinical write journey was
rerun in this publication pass. No sandbox exchange or production change occurred.

### Latest follow-up — inbox, attachments and public signing

The following records the earlier implementation checks; the publication retest
above is the latest browser evidence.

| Check | Result |
|---|---|
| Targeted backend checks | 71 passed: in-memory SQLite route/scope tests, offline signing and AST scope checks; **not** a PostgreSQL/storage integration gate |
| Frontend suite | 82 passed; includes inbox pagination/patient isolation, attachment validation/upload ambiguity, authenticated multipart and temporary downloads |
| Typecheck and scoped ESLint | Passed |
| Ruff on new backend modules/config/schemas/tests | Passed |
| Contract matrix | 214 frontend calls match OpenAPI |
| Live browser, new production build, real MinIO/PG round trip | At this earlier checkpoint, not rerun; the runtime blocker was open. See the newer scoped fix above. |

The inbox tests were first run before implementation and failed on the missing
endpoint. Query-validation assertions also verify that 422 identifies the query
field, not a UUID route parsing error. Actual MinIO SDK signing is tested offline
with synthetic credentials and public network calls forbidden; this verifies
URL construction/signing configuration, **not** a deployed certificate/proxy.

### Earlier first-slice results (before the follow-up above)

| Check | Result |
|---|---|
| Full backend gate on this branch | **1,512 passed**, four existing ABDM Pydantic alias warnings |
| Script tests | **14 passed** |
| Frontend tests | **71 passed**, including nine new adapter/form/state tests |
| Typecheck and scoped ESLint | Passed |
| Production frontend build | Passed |
| Contract matrix | **210 frontend calls** match OpenAPI |
| Explicit backend convention scan | Two application files; zero blockers/warnings |
| Ruff on changed schemas and order tests | Passed; no whole-backend lint-clean claim |
| Rendered browser UI acceptance | Initial run passed seven checks; **latest repeat failed overall** on a React runtime error despite seven workflow assertions passing |

### Earlier runtime blocker — resolved by the scoped follow-up above

The final repeat emitted **“Maximum update depth exceeded”**. The harness
correctly exited nonzero and left `completed: false`, `passed: false`. The
seven successful workflow assertions did not overrule that failure. At that
point the cause was not established by static hook inspection. The subsequent
burst-input regression and MUI-wrapper fix above supersede that diagnosis status.

The harness now captures each page error's stack and last completed check in
`browserErrors` so the next reproduction can identify the owning component.
An earlier diagnostic run was blocked by the approval service's usage limit.
Execution was restored during publication; the repeat reproduced the error and
captured the stack described above. That access problem is no longer the blocker.
That failed evidence remains intact. Changing input speed or suppressing page
errors would not constitute a fix; neither was used in the scoped follow-up.

The first-slice production build/typecheck passed, but neither proves runtime render
stability. The old merge-ready flag was not acceptance evidence. Fresh repeated
browser runs are now recorded above, and a new directory preserves each result.

The two initial backend regressions failed before the fixes: a moved-facility
retry returned 201, and the order response omitted fulfilment mode. The patient
switch regression was mutation-checked: replacing the session key with a
constant retained the prior patient's draft and failed the test. The real key
was restored and all nine new frontend tests passed again.

Backend tests include the existing PostgreSQL append-only trigger test; many
route/service fixtures use the existing SQLite test setup. Neither the new route
tests nor the UI transport simulation prove concurrent production result writes.

**Browser evidence is deliberately limited:** real local Next.js rendering and
real Keycloak login, but synthetic queue, encounter, order and result responses
are intercepted in Chromium. No clinical API mutation reaches the application
DB. The harness models a committed write followed by a lost response, proves
the identical key/body retry, receipt retention through parent refresh/read
failure, reload without duplicate submission and cancelled-order read-only UI.
It is not a persisted backend end-to-end journey or an ABDM milestone test.
Evidence: `docs/evidence/external-results-ui-20260910/external-results-ui.json`
and seven screenshots. No tokens or action keys are written to evidence.

## Remaining before F04 can close

1. **Real persisted acceptance.** With the result-input runtime error fixed,
   exercise the new Results tab/inbox and attachments
   against real PostgreSQL and MinIO. The existing simulated UI harness does not
   yet cover the new inbox or upload/download controls. Use a dedicated synthetic
   referral facility, not toggling a hospital's active modules. Include wrong,
   erased and foreign patient files, reload, and concurrent result submission.
2. **Storage deployment and upload reconciliation.** Provision the public HTTPS
   storage endpoint described below and prove byte-for-byte download. Unknown
   upload outcomes deliberately block; an administrator currently needs to
   reconcile existing file metadata/storage before proceeding. There is no new
   file-list/recovery screen or orphan-object cleanup job. Confirm virus-scanning
   and retention/recovery requirements separately; magic-byte validation is not
   a malware scan. Review the inbox query plan/indexes on representative PG data.
3. **Referred test identity.** The existing order header does not persist the
   clinician's specific outside test/study name. On reload it can only show the
   generic type and order number. A durable referral description is needed;
   do not invent local department items to hold it or claim it is already saved.
4. **Clinical review policy.** Outside intake is not local verification, sign-off
   or ABDM publication. Agree provenance, correction/review and date/timezone
   rules before exposing those claims. No nurse frontend path or new role grant
   was assumed in this slice.

## Public attachment deployment requirements

1. Provision a storage hostname owned by the deployment with a valid HTTPS
   certificate, proxying the MinIO S3 API (not the console). Keep buckets private.
   The existing application nginx files do not serve this hostname. Do not reuse
   the ABDM callback hostname by guessing an undocumented storage path.
2. Set `MINIO_PUBLIC_ENDPOINT` to that `host[:port]`, with no scheme, path,
   userinfo or query; set `MINIO_REGION` to the actual MinIO region (default
   `us-east-1`). Keep `MINIO_ENDPOINT` as the internal storage address. The
   production example deliberately leaves the public endpoint blank.
3. Preserve the **original Host, object path and complete query** at the storage
   proxy. Sign the public address from the start; do not substitute it into a
   URL signed for `minio:9000`. Avoid storing presigned query strings in proxy
   access logs. No anonymous bucket policy is required or authorized here.
4. On a synthetic patient's referral, upload a small genuine PDF, record the
   result, refresh, prepare/open its attachment, and compare the received bytes.
   Verify from the intended browser/workstation, not just inside Docker.
5. Confirm expired links fail and refresh correctly; wrong-patient and erased
   files must not open. Test maximum file size through nginx as well as directly
   against the backend (multipart framing contributes to nginx request size).

New code supports this configuration, but no hostname/TLS/public MinIO access
was provisioned or verified in this session.

## Reproduce

```bash
# Fast offline checks for the latest follow-up (not the full release gate):
cd backend
../.venv/bin/pytest -q tests/orders/test_external_referrals.py \
  tests/orders/test_external_results.py tests/test_file_download_signing.py \
  tests/test_cross_facility_reads.py tests/test_facility_scope_audit.py
cd ..

# Full gates once execution capacity is available:
make test-pg
make contract
cd frontend
npm test
npm run typecheck
npm run build
E2E_BASE_URL=https://localhost E2E_RUN_ID=external-results-ui-your-id \
  E2E_EVIDENCE_DIR=../docs/evidence/external-results-ui-your-id \
  npm run test:external-results-ui
```

Run heavy backend tests before browser tests. The UI harness is local-only and
does not require mutation authorization because clinical transport is simulated.
It is available as an explicit test command, not added to CI as a claimed real
clinical journey.
