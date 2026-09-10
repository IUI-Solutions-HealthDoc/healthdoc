# External-referral results — implementation progress, 10 September 2026

## Publication and scope

The preceding tariff-safety work was committed and published in
[PR #547 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/547),
with all four active CI checks passing. GitHub reported it merged during this
session; this session did not issue the merge command.

The referral work is on **`feat/external-referral-results`**, originally branched
from staging `43195e1` before #547 merged. On 10 September the user requested
commit/publication and a live local browser retest. It is being published as a
**draft PR into staging**, with the existing runtime blocker disclosed, not as
a merge-ready release. Integrate current staging `48dd47d` (#547) before review.
Earlier full-suite counts below predate that integration and exclude #547's
31 tariff-safety tests. This is **partial F04**, not closure of all referrals.

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

### Latest follow-up — inbox, attachments and public signing

| Check | Result |
|---|---|
| Targeted backend checks | 71 passed: in-memory SQLite route/scope tests, offline signing and AST scope checks; **not** a PostgreSQL/storage integration gate |
| Frontend suite | 82 passed; includes inbox pagination/patient isolation, attachment validation/upload ambiguity, authenticated multipart and temporary downloads |
| Typecheck and scoped ESLint | Passed |
| Ruff on new backend modules/config/schemas/tests | Passed |
| Contract matrix | 214 frontend calls match OpenAPI |
| Live browser, new production build, real MinIO/PG round trip | **Not rerun for this follow-up**; the earlier browser runtime blocker is still open |

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

### Open runtime blocker — do not publish as browser-accepted

The final repeat emitted **“Maximum update depth exceeded”**. The harness
correctly exited nonzero and left `completed: false`, `passed: false`. The
seven successful workflow assertions do not overrule that failure. The cause
is **not yet identified**; static inspection of the new hooks did not establish
a render loop, and no speculative library or application patch was made.

The harness now captures each page error's stack and last completed check in
`browserErrors` so the next reproduction can identify the owning component.
An attempted diagnostic browser rerun was rejected by the tool approval service
because its usage limit was reached. It was not bypassed. Browser reproduction
and validation need restored execution capacity or a developer-run capture.
No claim of a clean latest browser run is made.

The first-slice production build/typecheck passed, but neither proves runtime render
stability. The user has now requested publication; retain the PR as a draft
pending diagnosis and a clean repeated browser run. Use a **new** evidence directory to preserve the
failed run when reproducing.

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

1. **Browser render-depth failure and real persisted acceptance.** Diagnose the
   existing runtime error, then exercise the new Results tab/inbox and attachments
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
