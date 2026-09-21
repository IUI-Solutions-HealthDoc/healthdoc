# Ten-suite completion review — 20 September 2026

Status: **executing / not fully accepted**. Review target: development and PR
integration into staging, not a production deployment or a certification claim.

**21 September post-merge note.** Main `308660a` and staging `741a474` have
identical trees. The promotion conflict described below is historical. Suite
acceptance is unchanged. M1 consent, communication-mobile continuation,
address selection and the NHA card proxy are in progress on
`feat/abdm-m1-enrol-consent-mobile-address` and are not live acceptance.

## Answer

All ten suites are **not finished against their original acceptance criteria**.
Suites 1–9 have implementation commits covering HD-01–HD-36. Suite 10
(HD-37–HD-40) concerns genuine ABDM exchange, recovery, safety acceptance and
release evidence; earlier infrastructure and tests exist, but those outcomes
remain unproven. Counting 36 numbered packages as 90% completion is misleading.

The original implementer's “implemented/tested/review ready” entries are
historical claims, not independent acceptance. This pass found defects in
features already described that way. No suite receives new full clinical or
production acceptance merely from these fixes.

## Branch and PR

**Latest 21 September reconciliation:** #586 is merged at `c0113dc` and #587
(M1 resend/Aadhaar verification) at `5771931`, both into staging. Main is still
`9222f07` from #585. Remaining local error-message/evidence changes and the
historical review are consolidated on **release/staging-consolidation**; see
[branch reconciliation](branch-consolidation-2026-09-21.md). No suite verdict is
upgraded by publication. A code-owner approval and green latest-SHA checks are
required before integrating this follow-up, then opening staging -> main.

- Safety work branch: **fix/clinical-safety-keycloak-return**, delivered through
  [#584](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/584),
  **squash-merged into staging on 21 September (`dcd7d15`)**; staging was then
  promoted to main by [#585](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/585)
  (`9222f07`). Repository promotion, not a production deployment.
- The handoff's final tranche (atomic clinical write retries, HD-29/HD-30) was
  verified after that merge and is delivered separately as
  [#586](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/586),
  branch **fix/clinical-write-retry-safety** cut from `dcd7d15`. See the
  “21 September continuation” section below for its scope and evidence.
- Original Suite 9 workspace: **feat/suite-9-portal-terminology-a11y-m1**, base
  35d8cc4, preserved together with untracked PDFs, Updates.md and backend/uv.lock.
- Suite 9 was already squash-merged to staging as 6505e63 through PR #583.
- Main promotion must remain **staging → main**, after approval and integration.

## Suite-by-suite acceptance ledger

“Present” below means source implementation exists, not that every behavior
has been independently exercised against a live deployment.

| Suite | Packages | Present / repaired | Remaining to accept the entire suite |
|---|---|---|---|
| 1 | HD-01–04 | Role-aware arrival links, consent UI, nursing task transitions, non-OPD emergency/doctor entry. Consent stale-response and native-login fixes are in #584. | Current-revision populated role/visit handoffs and delayed-response browser acceptance; every supported visit type must preserve the intended clinical context. |
| 2 | HD-05–08 | Unassigned visit/token recovery; DOB-derived age display; address/guardian inputs; protected photo lifecycle. | Estimated-age precision beyond years, month/day recording when DOB is unknown, demographic edit concurrency/reason, and full photo replace/erase/authorization evidence. DOB display precision is not stored estimated-age precision. |
| 3 | HD-09–12 | Local patient card, counter/locale controls, appointment service/check-in and stale-visit reconciliation. | Recurring appointment series are not represented in the current appointment model; provider/counter authority, slot contention and reconciliation exemptions require acceptance. No approved teleconsult workspace should be implied. |
| 4 | HD-13–16 | Clinical disposition queues, ADT/bed picker, admission chart and checklists. | Full doctor-to-nurse handoff, independent admission contexts, transfer rollback and bed races; approved versioned checklist/shift generation, completion/correction and discharge lifecycle. |
| 5 | HD-17–20 | eMAR write/correction, ED triage, structured analytes, urgency. This pass serializes scheduled-dose writes on the prescription item. | Approved dose schedule identity/version and PRN/STAT/correction policy; ED protocols; lab rule approval/effective versions/age-sex rules. The analyte service still contains a legacy haemoglobin fallback; code availability is not clinical approval. |
| 6 | HD-21–24 | Durable alert records/ack, specimen handling, radiology attachments, pharmacy returns; ownership fixes in #584. | Cross-process rollback/restart/replay evidence; chosen LIS scope, analyzer/QC reconciliation; real synthetic DICOM/PACS round trip; return/refund/stock and expiry-exception governance. |
| 7 | HD-25–28 | Billing care setting and scheme-unavailable behavior, KPI producer/readers, OT lifecycle/checklists, program enrolment/follow-up. Timing KPI placeholders and patient scopes repaired. | Approved accrual/proration/source identities; real sanctioned payer integration remains unavailable; KPI definitions/revisions/historical occupancy; OT team contention and clinical checks. Program enrolment currently schedules a hardcoded 30-day review: replace with approved configurable policy rather than assuming it is universal. |
| 8 | HD-29–32 | Immunization, blood crossmatch/issue, forms, CSV, dead-letter and walk-in surfaces. Unsafe issue and payload mismatches repaired; typed form validation added. **#586:** atomic idempotent retries with stored receipts on the eight new writers, crossmatch-preserving issue retry, and honest failed/empty states on the forms, CSV, blood-bank and immunization pages. | Blood release independence, recall/transfusion traceability and adverse-event workflows; approved vaccine schedule; form governance/applicability/versioning. Order-set execution remains disabled pending mappings/writer; CSV supports vaccines only, not every advertised entity. Retry keys are not durable across navigation/reload. |
| 9 | HD-33–36 | Bound portal, terminology/specialty and print surfaces, M1 identity/Scan-and-Share. Ticket contract/lifecycle and unfinished-prescription exposure repaired here. | Privacy approval/withholding/proxy and revocation; terminology licensing/versioning/governance (current catalogue is curated, not a complete terminology service); patient-specific PDF/keyboard/zoom acceptance; genuine M1 assigned cases. Scan-and-Share profile retention/encryption and receipt provenance also need review. |
| 10 | HD-37–40 | HIP/HIU/FHIR/crypto/jobs/callback diagnostics, restore/security tooling, referral/financial/patient-switch harnesses and role manifests exist. | Genuine M2/M3 counterparty exchange and case evidence; sanitized production-derived restore/PITR and all-service recovery; real alert delivery, measured load/security closure and clinical/privacy/finance sign-offs; latest-SHA all-role action evidence and review. |

## Package-level next actions

These preserve the forty-package scope so a later agent cannot close a suite
by testing only its dashboard. An item labelled acceptance is not an assertion
that no code change will be needed when exercised.

| ID | Next verifiable outcome |
|---|---|
| HD-01 | Role-denied arrival links never mount or call privileged sections. |
| HD-02 | Browser A→B→A with delayed list/detail/create/transition responses cannot repopulate another patient. Hook regressions exist. |
| HD-03 | Accept/complete/duplicate/cancelled nursing orders under real contention; no diagnostic check-off bypass. |
| HD-04 | Every supported non-OPD visit reaches its permitted clinical workspace without inventing an OPD queue token. |
| HD-05 | No-roster and failed-token recovery do not create a second visit or fee. |
| HD-06 | Capture approved estimated-age precision without fabricating DOB; newborn input and storage agree. |
| HD-07 | Authorized demographic correction records reason and refuses stale version updates. |
| HD-08 | Real protected photo upload/replace/remove; wrong-patient and expired URL checks. |
| HD-09 | Scan a printed local identifier and verify patient/card merge resolution; no ABHA in barcode. |
| HD-10 | Authorized desk/counter behavior, bilingual form preservation and explicitly permitted vitals workflow. |
| HD-11 | Recurring scheduling model/workflow; provider optionality; real slot races and idempotent check-in. |
| HD-12 | Reviewed stale-OPD candidates exclude active clinical work/IPD/ED; repeat reconciliation has no extra effects. |
| HD-13 | Disposition request → allocation/discharge with cancellation, no-bed and duplicate handling. |
| HD-14 | Competing bed allocation and failed transfer rollback; no seed dependency for ward onboarding. |
| HD-15 | Two admissions of one patient remain separate; late chart responses cannot mix them. |
| HD-16 | Approved checklist generation/version, shift/due ownership, skip/correction history and concurrency. |
| HD-17 | PostgreSQL nurse contention gate passed at ab83a25. Approved schedule/dose/correction semantics remain: row locking is not a scheduling subsystem. |
| HD-18 | Approved triage scheme/history, disposition metrics and bounded break-glass/THID flow. |
| HD-19 | Versioned approved analyte rules and removal/replacement of unapproved fallback interpretation; independent verify/amend/FHIR read-back. |
| HD-20 | Real ED order priority survives delivery and fulfilment; approved medication acknowledgement rules. |
| HD-21 | Writer/reader process separation, no alert on rollback, reconnect replay and durable acknowledgement. |
| HD-22 | Agree in-app LIS versus external adapter; specimen/QC/catalogue and duplicate/unmapped/outage tests. |
| HD-23 | Authenticated PACS study correlation/view/report and protected attachment alternative. |
| HD-24 | Reconcile original issue, partial return, stock disposition and financial reversal with retries. |
| HD-25 | Approved care-accrual rules; sanctioned payer integration or explicit unavailable state; independent refund approval. |
| HD-26 | Publish reconciled KPI definitions/periods/revisions; historical occupancy cannot be inferred from today's bed mirror. |
| HD-27 | Theatre/team contention, accountable surgical notes, module-off enforcement and approved safety checklist. |
| HD-28 | Replace universal 30-day review with approved program scheduling; sensitive-program permissions and audited exit. |
| HD-29A | Approved immunization catalogue, repeat/correction/recall rules and truthful certificate. |
| HD-29B | Independent screening release, unit/crossmatch/issue/transfusion traceability and recalls; current issue checks are not a complete blood bank. Donor/unit/crossmatch/issue writes are now idempotent with receipts and an issue retry cannot create a second crossmatch (#586). |
| HD-30 | Govern/version forms and approved code-mapped order-set writer; complete intended CSV entities. Transactional idempotent submissions/definitions/CSV import are implemented and verified with real PostgreSQL contention (#586); governance and the writer are not. |
| HD-31 | Prove durable jobs/receipts survive restart; replay cannot bypass consent/quota; review protected historical payload retention. |
| HD-32 | Walk-in diagnostic/pharmacy completion, accountable author, no duplicate fee or prescription bypass. |
| HD-33 | Unreleased prescriptions now refused; finish withholding/proxy/version/revocation and release-policy acceptance for every document type. |
| HD-34 | Licensed versioned catalogue and tariff/FHIR mappings; safe retired/unmapped codes, not assumed support from a short lookup list. |
| HD-35 | Actual rendered patient-specific PDFs, keyboard/focus, 200% zoom and mobile; no fake accreditation or signatures. |
| HD-36 | Current participant authorization and private OTPs; genuine M1 case ledger. Reception code tests are synthetic, not NHA evidence. |
| HD-37 | Confirmed link → PHR consent → encrypted exchange → independent decrypt/validate/view → receipt plus deny/revoke/expire/retry cases. |
| HD-38 | Production-derived sanitized rehearsal, PITR plus other stores/keys, received alert, safe load/security measurements and named approvals. |
| HD-39 | Populated referral attachment journey and tariff/patient/invoice switch/fault-injection acceptance on current deployed SHA. |
| HD-40 | Preserve dated failures/success manifests, collect every role's actions/read-back, green latest-SHA CI and human review before promotion. |

## New changes in this continuation

1. Scan-and-Share desk consumes the actual API array and actual fields; sends
   counter, not ignored counter_id/operator_id. It uses immutable ticket IDs.
   Duplicate short tokens return 409 rather than choosing a patient.
2. Active queues exclude expired tickets; expired/inactive check-in is refused.
   Ticket row locks prevent counter reassignment. Same-counter retry returns the
   original timestamp. Migration **0082** stores that time; old unknown times
   stay null. Check-in does not create a visit or charge.
3. Desk selection/list/lookup responses are scoped; closing resets state.
   Confirmed check-in reads back before handing the bound patient to StartVisit.
   Printed QR contains only the opaque ticket ID, not ABHA/contact data.
   Removed invented counters, accreditation, fake barcode and synthetic DOB.
4. Form definitions reject unsupported types, executable/unknown attributes,
   duplicate field/option IDs and invalid option lists. Submission validates
   stored-version types, finite numbers, exact dates/options and unknown keys
   before writing; no clinical ranges are invented.
5. Dynamic form checkboxes retain boolean state; numeric controls allow
   decimals. Changing patient/visit/form/version resets the editor and ignores
   previous asynchronous completion. Old historical submissions are unchanged.
6. Patient portal prescriptions require a finished encounter and coherent
   patient/facility/visit ownership for both lists and guessed detail IDs.
   This reuses the existing prescription finalization boundary used by ABDM;
   it does not establish a new privacy-withholding policy.
7. eMAR takes a prescription-item lock before duplicate-dose checking, refuses
   missing/stopped items and distinguishes corrections. New PostgreSQL gates
   exercise two sessions, not just sequential SQLite calls.
8. Corrected the migration-map documentation format that failed the first
   backend CI run. The first run's frontend and browser job passed; its failed
   backend job stopped before tests and must not be described as a backend pass.
9. Corrected two package-relative regression-test imports found by the next
   CI run. Local `PYTHONPATH=.:tests` had masked the collection failure. Without
   that override, all 2054 tests collect and both affected files pass (30 tests).
   The CI configuration and test gates were not relaxed.

## 21 September continuation — atomic clinical write retries (PR #586)

Scope: the handoff's last tranche for HD-29/HD-30 ("idempotent uncertain write
outcomes") plus the page-state defects it listed as identified-not-fixed.

1. `backend/app/common/clinical_write.py` fronts `POST /forms/definitions`,
   `/forms/submissions`, `/admin/csv/import`, `/immunization/records`,
   `/blood-bank/donors`, `/units`, `/crossmatch` and `/issue`. Bounded
   `Idempotency-Key` required; `INSERT … ON CONFLICT DO NOTHING RETURNING`
   reservation on `idempotency_keys`; write and receipt commit together;
   identical retry replays; changed payload/facility → 409 `idempotency_key_reuse`;
   unconfirmed original → 409 `idempotency_key_in_progress`; patient-role
   sessions refused; resource authorization before replay; receipt failure
   rolls the write back; integrity errors → 409 `clinical_write_rejected`.
   Services flush; the immunization catalogue seed no longer commits or
   swallows failures inside a clinical transaction. No migration.
2. `frontend/src/lib/useClinicalWrite.ts` keeps one immutable body/key per
   mounted editor, blocks double submission, keeps the key after uncertain
   outcomes, frees it only on explicit pre-write refusal, drops late
   completions after unmount and exposes `isPending()` synchronously. Editors
   lock and offer “Retry unchanged save”. A confirmed crossmatch survives an
   uncertain issue and only the issue is retried. No browser storage: the key
   lives only while the editor is mounted.
3. Forms/immunization search selects only an exact single match and reports
   zero/multiple/failed searches; placeholders no longer advertise name search.
   Failed history, definitions, inventory and catalogue reads are shown as
   failures with retry, never as empty data. A forms refresh after CSV import
   no longer unmounts an in-progress draft. CSV FileReader results and
   validation verdicts that outlive their draft are discarded.
4. New CI browser gate `npm run test:clinical-write-ui`: real Keycloak
   sign-in, rendered forms and blood-bank pages, intercepted synthetic
   clinical transport (lost form response; crossmatch-success/issue-failure).

Evidence, 21 September, isolated local environment (not CI, not live clinical
acceptance):

- `tests/test_clinical_write_retries.py`: **36 passed** (SQLite).
- `tests/test_clinical_write_postgres.py`: **2 passed with two real PostgreSQL
  connections** — duplicate same-key request waits and returns one
  record/receipt; first-request rollback lets the retry complete once —
  against `healthdoc_test` migrated to 0082 inside an isolated compose project
  (`COMPOSE_PROJECT_NAME=healthdoc-cw`, fresh volumes; the dev `healthdoc`
  project, its containers and data were not started or touched).
- Receipt-failure regression proven sensitive: `create_submission` mutated
  flush→commit fails it with one surviving row; restored and re-run.
- Focused retries + clinical safety + Suite 8 backend: **73 passed**. Broad
  non-infra backend sweep: **1010 passed, 350 skipped**; the one failure
  (`git init` inside pytest's temp dir) is a sandbox restriction and passes
  unsandboxed.
- Frontend `npm test`: **162 passed** (152 + 10 new page-state regressions in
  `tests/clinical-page-states.test.mjs`); exact-match rule mutation-checked.
  `tsc --noEmit`, changed-source ESLint, `pr_check.py` (0 blockers; remaining
  idempotency warnings on Scan-and-Share check-in, specialty assessment,
  order-set apply, CSV validate, KPI produce) and `fe_check.mjs` (0 blockers;
  UTC-display warnings remain in immunization certificate/schedule views).
- `npm run test:clinical-write-ui`: **passed 4/4, zero page errors, twice**.
  Evidence JSON/screenshots kept outside the repository.
- Docker is available on this Mac; earlier “Docker unavailable” statements in
  this file are historical.

Limits: no full `make test-pg`-equivalent run on this host; no all-role
browser acceptance; no live ABDM operation; retry keys are not durable across
navigation or reload; #586's own CI on its latest SHA is the gate that counts.

## Evidence and limits (20 September)

Commands run from the isolated branch worktree; no production records changed.
Fresh outcome counts and final CI state are maintained in CLAUDE.md / PR #584
(now merged) and PR #586.

- Frontend unit/component suite: 136 passing, zero skipped; TypeScript and
  changed-source ESLint pass.
- Focused Scan-and-Share/backend Suite 9: 20 passing.
- Forms/Suite 8/Scan-and-Share focused backend: 43 passing.
- Portal/eMAR/Suite 9 focused backend: 29 passing; one PostgreSQL test skipped
  locally because no explicit TEST_DATABASE_URL was configured.
- Schema drift: zero blockers/warnings. Spec check: 133 tables, 68 enums.
  Migration chain: 89 revisions, linear head 0082; 0081→0082 offline SQL passes.
- Route-existence contract: 311 calls valid; this does not validate wire bodies.
- Negative test proof: disabling the Scan-and-Share expiry guard made the
  time-expired check-in test fail with HTTP 200 instead of 409; guard restored.
- Local Docker daemon unavailable and Java runtime missing. Full PostgreSQL,
  Redis/MinIO, browser/restore and Java crypto gates must use the configured
  isolated stack/CI. Explicit skipped/excluded tests are not passes.
- Convention warnings about other write endpoints' idempotency remain.
- Subsequent isolated CI at **ab83a25**, run
  [35505210441](https://github.com/IUI-Solutions-HealthDoc/healthdoc/actions/runs/35505210441):
  **2054 backend tests passed, zero skipped, 7 warnings; 36 script tests passed**.
  Both new PostgreSQL contention tests executed. Migrations through 0082,
  Redis/MinIO and the Java-backed crypto suite ran there, not on the local Mac.
  Frontend (136 tests plus build), release-policy and the **entire browser job
  passed**: auth/bearer, print/PDF, per-dashboard smoke, invoice-switch,
  external-results, ABDM PDF/consent-refresh, tariff and superadmin gates.
  Four required checks are green; the weekly Electron job was skipped.
  This is not a genuine ABDM exchange, all-function clinical acceptance or
  production restore. Check latest PR gates after the documentation update.

## Deployment and human/external gates

Apply **0081 and 0082 before deploying this backend**, rebuild frontend/backend
together, and review the existing Keycloak client's standard-flow/S256 settings
without importing over users/roles/secrets. Keep feature→staging→main policy.

The acceptance-orchestrator and verification skills keep this status partial:
every acceptance criterion needs evidence; code and passing unit tests do not
authorize clinical policy, production deployment or certification claims.

Needed inputs: named clinical/lab/pharmacy/finance/privacy approvals; approved
catalogues/order mappings/program schedules; isolated runtime and sanitized
production rehearsal material; current participant/PHR authorization, genuine
requester identity and NHA-assigned cases/counterparty. No new linking token,
OTP, consent submission or outbound-worker start was authorized or performed.

M1, M2 and M3 remain **not independently accepted/certified**. Historical
consent through 14 September is expired. Support-response status was not
rechecked; the last owner's report was no response. Keep callbacks, local
synthetic replay, HTTP 202 and genuine NHA/counterparty transactions distinct.
