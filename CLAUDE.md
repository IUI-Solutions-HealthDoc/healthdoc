# HealthDoc HIMS — working notes

Hospital management system for Indian facilities. FastAPI + PostgreSQL backend,
Next.js 16 + Electron frontend, Keycloak OIDC, all behind nginx in Docker
Compose. Targeting ABDM certification and a CERT-In WASA audit.

## Current project status — ten-suite acceptance and safety fixes, 20–21 September 2026

**This section supersedes the dated 18 September review below. Implementation
has advanced substantially; acceptance and ABDM certification have not been
established by counting commits or test cases.**

### 21 September continuation — clinical write retries, PR #586

- **PR #584 was squash-merged into staging** on 21 September at 06:26 UTC as
  `dcd7d15`, and [PR #585](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/585)
  promoted staging → main (`9222f07`) at 06:52 UTC. Both happened before the
  handoff's final tranche was verified, so that tranche is **not** in staging
  or main. It is delivered as
  **[PR #586 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/586)**,
  branch `fix/clinical-write-retry-safety`, cut from `dcd7d15` with two commits
  (`1d6a1ee` atomic retries, `7475fb3` page states). Repository promotion of
  #584/#585 is not evidence of a production deployment. The old branch
  `fix/clinical-safety-keycloak-return` carries one now-superseded extra commit
  (`fe564cc`, same content as `1d6a1ee`) pushed before the merge was noticed;
  it can be deleted after #586 merges — do not open a PR from it.
- **Atomic idempotent clinical writes** (`backend/app/common/clinical_write.py`)
  now front eight endpoints: forms definitions/submissions, admin CSV import,
  immunization records, blood donors/units/crossmatch/issue. A bounded
  `Idempotency-Key` is required (422 without it); the reservation row is taken
  with `INSERT … ON CONFLICT DO NOTHING RETURNING` so a concurrent duplicate
  waits instead of racing; write and receipt commit together; an identical
  retry replays the original response; changed payload/facility → 409
  `idempotency_key_reuse`; unconfirmed original → 409 `idempotency_key_in_progress`;
  patient-role sessions are refused; resource authorization runs before any
  replay; receipt failure rolls the write back; integrity errors → 409
  `clinical_write_rejected`. Services flush, the router owns the transaction.
  No new migration; head stays **0082**.
- **Frontend `useClinicalWrite`**: one immutable body/key per mounted action,
  double-submit blocked, key kept after network/5xx/ambiguous outcomes, freed
  only on explicit pre-write refusal, late completions dropped after unmount,
  `isPending()` readable synchronously. Editors lock and show “Retry unchanged
  save”. Crossmatch-success/issue-failure retries only the issue. Nothing is
  stored in the browser: **the retry key survives only while the editor stays
  mounted**; after navigation or reload the user must reconcile saved records.
- **Page states**: forms/immunization patient search selects only an exact
  single match (zero/multiple reported, never first-match), search failures
  are shown, placeholders say UHID/mobile (no name search exists on that
  request); failed history/definitions/inventory/catalogue reads render as
  failures with retry, not “0 records”, “(0)” or empty tables; a forms refresh
  after CSV import no longer unmounts an in-progress draft; CSV FileReader
  results and validation verdicts that outlive the draft they describe are
  discarded through render-independent guards.
- **Verified on the PR tree, 21 September, local isolated environment:**
  retry suite 36 passed (SQLite); **both real PostgreSQL contention cases
  passed** (two connections: duplicate same-key waits → one record/receipt;
  first rollback → retry completes once) against `healthdoc_test` migrated to
  0082 in an isolated compose project (`COMPOSE_PROJECT_NAME=healthdoc-cw`,
  fresh volumes, the dev `healthdoc` project and its data untouched); receipt
  rollback test proven sensitive by a flush→commit mutation; focused
  retries/safety/Suite 8 backend 73 passed; broad non-infra backend sweep
  1010 passed / 350 skipped in the sandbox with one sandbox-only `git init`
  failure that passes unsandboxed; frontend **162 passed** (152 + 10 new
  page-state regressions, exact-match rule mutation-checked); `tsc`, ESLint,
  `pr_check.py` and `fe_check.mjs` clean with only pre-existing warnings on
  other endpoints; **new browser gate `test:clinical-write-ui` passed 4/4 with
  zero page errors, twice**, with real Keycloak sign-in and intercepted
  clinical transport. Docker **is** available on this Mac now; the older
  “Docker unavailable” notes below are historical. Check #586's own CI on its
  latest SHA before relying on any of this; local results are not CI.
- Still open from this tranche's scope: `pr_check.py` idempotency warnings on
  `check_in_scan_share_ticket`, `record_encounter_specialty_assessment`,
  `apply_order_set` (currently always 409), `validate_admin_csv` (read-only)
  and `produce_kpis`; `fe_check.mjs` UTC-display warnings in the immunization
  certificate/schedule views. None of the HD package verdicts below change:
  HD-30's “idempotent uncertain write outcomes” item is now implemented and
  verified for the eight writers, its governance/order-set/CSV-entity items
  are not.

### 20 September review

- Reviewed base: `35d8cc4` on `feat/suite-9-portal-terminology-a11y-m1`.
  Work was isolated on **`fix/clinical-safety-keycloak-return`** in a separate
  worktree; the implementing agent's original branch and untracked files are
  preserved. Staging 6505e63 (Suite 9 squash PR #583) was integrated on this
  safety branch and delivered through **[PR #584 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/584)**
  (merged 21 September, see above). No production deployment or participant
  operation has been performed.
- Suite 7 (HD-25–28), Suite 8 (HD-29–32) and Suite 9 (HD-33–36) implementation
  commits are now present. The older statement that only HD-01/02 have been
  implemented is no longer current. HD-01–36 are **not 36 accepted packages**:
  there are incomplete features, negative-case defects and policy decisions
  within those packages. Do not label the product “90% complete” on that basis.
- Full review, verified results, deployment order and remaining work:
  [ten-suite / all forty packages acceptance ledger](docs/ten-suite-acceptance-status-2026-09-20.md)
  and [earlier clinical safety review](docs/clinical-safety-review-2026-09-20.md).
  **All ten suites are not complete.** Suites 1–9 contain implementation;
  Suite 10 and material parts of earlier suites still need implementation,
  live acceptance or approved policy. The detailed ledger distinguishes these.

### Safety changes on this branch

| Area | Current implementation / boundary |
|---|---|
| Patient isolation | Forms and immunization reads/writes check facility and verified, non-revoked self binding for patient-role accounts. OT/program/return creation checks the patient; visit/admission, dispense and radiology attachment references are checked against their owning resources. |
| Suite 9 specialty assessments | Added missing clinical role gates. Encounter and visit must both belong to the caller's facility; patient-role credentials cannot acquire staff access by carrying an additional role. Inconsistent historical assessment ownership is not silently reassigned. |
| Blood issue | Rechecks current screening, available status, facility-day expiry, recipient scope and compatible crossmatch while locking the issue rows. Pending/failed screening, expired, quarantined, discarded and reserved units are refused. Legacy facility scope derives from the donor creator; unowned rows fail closed. |
| UI contracts | Blood and immunization payloads match backend field names. Compatibility must be selected explicitly and is reset on recipient change. Vaccine submission sends a code and timestamp, with batch expiry. No invented digital-signature or issue-slip claims. |
| False success | Order sets are **preview-only**, with API 409 until catalogue mappings and an actual transactional order writer exist. CSV imports are restricted to implemented vaccine writes; unsupported entity imports fail. This is safe restriction, not feature completion. |
| KPI truthfulness | OPD wait uses visit/first-encounter timestamps, lab TAT uses collection/first verify audit event, ED acuity uses recorded triage. Missing measurements stay unavailable. **Migration 0081** adds timing calculation provenance; legacy values remain stored but are hidden until recalculated. |
| Consent context | List, detail and access-history hooks reject stale callbacks/responses, including A → B → A. Late creation cannot select A's record in B; changing patient/record remounts mutation UI and suppresses stale success notifications. |
| Keycloak | Native themed authorization-code + S256 PKCE login via this deployment's origin, with safe original-route/query/fragment return. Password grant/manual token restoration removed; legacy `hd_rt` storage cleared. Realm template disables direct grants. Existing deployed realms still need the explicit configuration change. |
| Scan-and-Share desk | Correct array/field/counter contract; immutable ticket UUIDs; ambiguous short tokens refused; expiry/status/patient scope checked. Locked same-counter retries preserve original check-in time (0082); counter reassignment refused. Confirmed read-back hands the bound patient to StartVisit. No fake accreditation, counters/DOB, barcode, or ABHA in printed QR. |
| Forms | Definitions and stored-version submissions validate supported types/options, unique IDs, finite numbers and actual dates before writes. Boolean/decimal controls repaired; patient/visit/form switches discard old completion. Order-set writer, general CSV and governance remain incomplete. |
| Portal release | Prescription list/detail require a finished encounter with matching patient/facility/visit, reusing the existing ABDM finalization boundary. Privacy withholding/proxy approval is still outstanding. |
| eMAR contention | Prescription-item row lock precedes duplicate-dose check; missing/stopped items refused and corrections distinguished. The real two-session PostgreSQL regression passed in CI; approved scheduled-dose/PRN policy is still not supplied by this patch. |

### Validation and release boundary

- Earlier focused safety backend suite: **63 passed**. Continuation focused
  forms/Suite 8/ticket suite: **43 passed**; portal/eMAR/Suite 9: **29 passed,
  one PostgreSQL test skipped locally**. Frontend suite: **136 passed**. TypeScript and
  ESLint on changed source pass. Route contract check: **311 valid calls**;
  this checker does not validate payload shape or prove live authorization.
- Migration chain: **89 migrations, linear, head 0082**; PostgreSQL offline
  upgrade SQL generated successfully. No migration applied to the user's local
  or production database; CI at ab83a25 applied through 0082 in its disposable DB.
- Latest non-ABDM/backend sweep: **975 passed, 348 skipped** with infrastructure
  test files explicitly excluded; exact command and earlier failures are in the
  review. Repeated without a PYTHONPATH override with the same counts. Schema
  drift: zero blockers/warnings. This local run alone is not PostgreSQL/browser acceptance:
  Docker daemon is unavailable; host Java runtime is missing; socket-dependent
  Redis/SSE tests and backup configuration need their real test environment.
- Convention checks have **zero blockers but remaining warnings** about
  idempotency and date presentation. Do not describe them as warning-free.
  The new row-lock regressions subsequently passed with concurrent PostgreSQL
  sessions in the isolated CI environment (see revision-specific result below).
- Initial PR CI at e33e1d0: frontend, release-policy and nurse-auth/browser job
  passed. Backend stopped at spec drift because the new migration map used a
  column name as a table. Fixed the documentation format; local spec check now
  passes (133 tables, 68 enums). Check the **latest PR SHA**, not that older run.
- Follow-up CI at 915083f passed the spec/schema/contract gates and frontend,
  but backend **did not execute tests**: two regression modules imported sibling
  tests as top-level modules. The earlier local `PYTHONPATH=.:tests` command
  masked that collection error. Imports now use the `tests` package; with
  `PYTHONPATH` unset, **2054 tests collect** and the two affected files have
  **30 passing tests**. Do not add `tests/` to CI's import path to hide this.
- **Verified CI application revision ab83a25**, run
  [35505210441](https://github.com/IUI-Solutions-HealthDoc/healthdoc/actions/runs/35505210441):
  backend **2054 passed, zero skipped, 7 warnings**, plus **36 script tests**.
  This includes actual PostgreSQL eMAR/ticket contention, migrations, Redis,
  MinIO and Java crypto gates. Frontend **136 passed, zero skipped**, build,
  and release-policy passed. The **complete nurse-auth-e2e job passed**:
  staff/patient authentication and bearer requests, print/PDF, per-dashboard
  smoke, invoice-switch, external-results, ABDM PDF/consent-refresh, tariff
  maintenance and superadmin isolation. All **four required checks passed**;
  the weekly Electron job was **skipped**, not passed. Some workflow transports
  are deliberately synthetic/intercepted: this is not all-role clinical or
  NHA certification. A subsequent documentation-only commit does not constitute
  a new application test run; always check its latest PR gates too.
- Before deployment: migrate to **0082**; rebuild backend/frontend together; apply
  the existing realm's native-flow settings without overwriting users; test
  deep-link login, logout/expiry, required actions/MFA, and all changed clinical
  actions. Do not promote directly to main; retain staging/review gates.

### ABDM M1 / M2 / M3 — unchanged live acceptance boundary

| Milestone | Built / historical evidence | Still required |
|---|---|---|
| M1 | Identity/OTP UI and backend, historical existing-ABHA verification/binding; Scan-and-Share reception contract/expiry/retry fixes now have synthetic regression coverage. | Full assigned NHA cases with a currently consenting participant, private OTP entry, persisted identity read-back and negative cases. Real profile-share/counter acceptance and protected profile retention remain; synthetic ticket tests are not live NHA evidence. |
| M2 | v3 callbacks, outbound linking, document-scoped care contexts, durable transfer jobs, FHIR export/encryption and callback diagnostics. | Genuine confirmed link, PHR visibility/consent, clinical transfer and recipient receipt, plus rejection/expiry/retry evidence. Owner's latest report was no support response; no inbox or gateway recheck here. Mediated linking still needs an approved SMS/OTP relay. |
| M3 | Consent/artefact APIs, encrypted receive/decrypt handling, protected viewer and requester-identity fields. | Genuine/NHA-approved clinician metadata, PHR approval/denial, authorized counterparty exchange, view/receipt, revoke/expire/retry evidence and NHA assessment. |

**No new milestone was executed or certified in this pass.** Historical consent
through 14 September is expired. Never restart outbound jobs or reuse that
consent without checking current authorization and queued work. HTTP 202,
synthetic callbacks, local crypto tests and a working dashboard are not
substitutes for a completed sandbox round trip.

### Remaining completion work, in order

1. Run the deployment/browser/PostgreSQL acceptance checklist in the new review.
   Idempotent retry/concurrency handling for the eight new Suite 8 writers is
   implemented and verified in PR #586; the remaining write endpoints flagged
   by `pr_check.py` (Scan-and-Share check-in, specialty assessment, KPI
   produce) still need the same treatment or a documented read-only exemption.
2. Obtain clinical approval for blood donor eligibility, immunization schedules,
   analyte/reference rules, specialty templates and terminology provenance.
   The presence of seeded defaults is not that approval.
3. Implement approved order-set catalogue mappings and real atomic writes;
   other CSV entity importers remain disabled rather than claiming success.
4. Finish HD-37–40 evidence: ABDM cases, production-derived restore/PITR and
   non-Postgres recovery, real alert delivery, clinical load/security review,
   referral/tariff/patient-switch acceptance, accessibility/print and all-role
   populated workflows. These also revisit incomplete parts of HD-01–36.

## Historical project review — 18 September 2026 (superseded snapshot)

**Read this section before the historical notes below. HealthDoc is not fully
finished, production-approved or ABDM-certified.** This is an independent source
and targeted-test review, not a new all-role browser or NHA acceptance run.
No application fix, deployment, participant operation or PR mutation was made
in this documentation pass.

### Revision, delivery and evidence boundary

- Reviewed application HEAD: `4ec81b8798989d0ae05644c0882dd0fddbbb624e`, branch
  `feat/login-split-screen-hims-branding`. The login/branding work was committed
  during this review; it is separate from the Bahmni handoff fixes.
- [PR #559](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/559)
  delivered callback diagnostics to staging; #560 promoted staging to main.
- [PR #561](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/561)
  delivered `9b2a771` (reception/consent) and `d9d8dd3` (superadmin landing wait).
  GitHub confirms merge into staging on 18 September at 15:40 UTC, approval,
  four successful checks (release-policy/backend/frontend/nurse-auth-e2e), and
  **electron-shell skipped**, not passed.
- [PR #562](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/562)
  promoted staging to main at 16:00 UTC, merge `e84bd753684542de987e600aa99f43c6733bb99e`.
  This is repository promotion, not proof of a production deployment.
- [PR #563](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/563)
  contains the new in-place credentials login and HIMS branding. At the review
  snapshot it is open against staging and approved; release-policy passed,
  backend/frontend/nurse-auth-e2e were running, Electron skipped. Re-read its
  latest SHA/checks before any decision. Approval does not resolve the findings below.
- `Issues/` remains untracked locally. Do not assume its handoff, PDFs or agent
  ledger are in a merged PR. Preserve unrelated work and do not stage everything.

### What the other agent actually completed

The four-PDF comparison defines **40 work packages**, not 40 equal-size bugs or
a whole-product percentage. Only **HD-01/HD-02 were implemented and HD-03 was
retested** in the new handoff work. HD-04–HD-40 have no new completion evidence
in that agent's ledger. Existing foundations in those packages still count;
“not newly completed” does not mean “nothing implemented.”

| Package | Confirmed improvement | Independent review verdict / next action |
|---|---|---|
| HD-01: post-visit actions | Billing link now checks `canRoleAccessPath`; queue link is OPD-only; desk handoff copy added | **Partial, changes required.** New `/emergency` and `/ipd` links remain unconditional for those visit types, but receptionist's route map allows neither. Replace with permitted handoff/context, without broadening privileges. Teleconsult copy promises a scheduled notification with no implemented scheduling/notification path. |
| HD-02: consent labels/context | Backend list/get/create enrich purpose code/description; channel labels are human-readable; list adds request sequencing | **Partial, changes required.** The actual hook still returns A's rows on the first B render and a retained A `refresh()` can overwrite B after B loads. Missing purpose falls back to invented “General Clinical”; show unavailable/unknown instead. Review detail and mutation callbacks too; add regression tests for the whole patient context. |
| HD-03: nurse Accept/Complete | Agent reports successful live acceptance/completion after staff provisioning; existing service tests pass | **Happy path only; not closed.** `complete_order` changes cancelled orders to completed and lets a lab order complete without a diagnostic result. No row lock or compare-and-set protects simultaneous completion. Prove state/type/ownership/facility/race refusal, not just removal from the pending table. |

Review locations: `frontend/src/features/receptionist/StartVisit.tsx`,
`frontend/src/lib/auth/routes.ts`, `frontend/src/features/consent/hooks/useConsentRecords.ts`,
`useConsentDetail.ts`, consent list/detail components, and
`backend/app/nursing/{router,service}.py`.
The original Accept-500 cause is not independently established by a successful
retest; do not present staff provisioning as the proven cause of every prior 500.
HD-03's reported lab “Mark completed” action is precisely why fulfilment semantics
need review: an HTTP 200 is not evidence that a diagnostic investigation occurred.

The agent ledger reports browser screenshots in `.tempmediaStorage`/execution
history but does not provide a complete committed evidence bundle for the
negative cases. Its “complete” statements are implementer claims, not this
reviewer's acceptance. See [implementation specification](Issues/Updates.md)
and [agent change log](Issues/Agent-Change-Log.md); this newer review qualifies
their earlier status statements without erasing the original record.

### New authentication branch: release blockers, not cosmetic changes

Commit `4ec81b8` changes the security/session architecture as well as branding:

1. `loginWithCredentials()` sends a password grant directly from the application;
   `healthdoc-frontend.directAccessGrantsEnabled` changes to true. The production
   realm renderer currently inherits that flag while requiring TOTP. The new
   form has no OTP/required-action flow. Prefer the existing themed Keycloak
   browser/PKCE path; do not claim production MFA support from dev password login.
2. Refresh tokens are persisted as `sessionStorage.hd_rt`, contradicting the
   prior memory-only credential boundary. Tab storage is still script-readable.
   Expiry-failure paths clear the access token but not this stored refresh token;
   explicit logout does remove it. Resolve persistence/expiry/revocation policy
   and test it rather than describing all tokens as memory-only.
3. `LoginScreen` accepts any return path starting with `/`. `//example.invalid/`
   passes and resolves off-origin. Use the existing safe internal-return-path
   approach, enforce same-origin and test protocol-relative/backslash cases.
4. Direct login/restoration manually assigns Keycloak token fields. It bypasses
   the installed SDK's `setToken` bookkeeping (including time skew and expiry
   timer), and SDK refresh does not persist a rotated `hd_rt`. Test token expiry,
   rotation, reload, logout, session revocation and production required actions.
5. Existing login tests and real-SSO smoke gates do not establish correctness of
   the newly added credentials form. Add action-level tests; do not weaken the
   old SSO tests to get green checks.

Do not promote this auth change on the strength of green unrelated tests.
Keep the HIMS visual naming changes separate from approval of the login mechanism.

### Project functionality: built versus unfinished

The 15 foundations listed in `Issues/Updates.md` exist: Keycloak/role boundaries,
registration/search/UHID, roster/queue, OPD notes/orders/prescribing, admission/
bed/transfer/discharge, nursing observations/tasks, lab results/verify/amend/MIS,
radiology workflow, external results intake, pharmacy/stock, PO/GRN/indents,
separate billing/tariffs/refunds, THID/maker–checker, consent/audit/DPDP/portal
binding, and the ABDM integration framework. Preserve these; do not rebuild them.

| Remaining scope | Handoff IDs | Current limit / next delivery |
|---|---|---|
| Core access | HD-04–05 | Doctor consultation still requires an OPD `token`; ED/IPD care needs authorized visit context. THID creation is not emergency arrival/treatment. Roster creation exists; improve no-roster guidance and recovery of visits whose token failed. |
| Reception | HD-06–12 | Age precision, address/guardian editing, protected photo, cards/barcode, counter/locale, appointments/follow-up/waitlist and stale-visit reconciliation remain partial/new. Reuse existing fields; scheduling and closure policy need owners. |
| IPD/nursing/emergency | HD-13–18 | Clinical disposition queues, visit picker, ward onboarding/care chart, checklists and ED triage remain. eMAR page is still read-only despite write APIs; dose identity, concurrency and clinical scheduling need design/approval. |
| Diagnostics | HD-19–23 | Structured approved analytes/ranges, durable cross-process critical alerts, LIS depth and proven PACS/upload journeys remain. Urgent/STAT orders already exist. Critical thresholds still contain a placeholder haemoglobin rule; live alert queues remain process-local. |
| Stock and finance | HD-24–25 | FEFO, PO/GRN and tariffs exist; close partial/return/concurrency acceptance, expiry-exception policy, care-setting accrual and claims. PM-JAY eligibility remains a stub, not scheme integration. |
| Further product depth | HD-26–30, HD-32–34 | KPI producers, reception/ED MIS, appointments-linked service-only arrivals, released portal documents, forms/order sets/terminology and approved OT/programs/immunization/blood-bank scope. OT/blood-bank guarded pings are not implemented modules. |
| Integration operations | HD-31 | Keep ABDM jobs/diagnostics; finish operator/dead-letter workflows and legacy FHIR outbox plaintext `payload=bundle` producers/cleanup. Receiver logging is not milestone completion. |
| Acceptance and operations | HD-35, HD-38–40 | Actual role actions, accessibility/print, referral/tariff/switch read-back, production-derived restore/PITR, alert receiver, clinical load/security review and named approvals. Existing test counts do not waive them. |
| ABDM | HD-36–37 | M1/M2/M3 status and exact blockers below. |

This is weeks-to-months of optional and core work across several disciplines,
not evidence of a one-day finished product. Freeze launch scope and estimate
individual accepted slices; do not assign a percentage by counting packages.

### ABDM M1, M2 and M3 — separate implementation from acceptance

**No milestone is certified by the evidence currently in the repository.**
The owner reports no support-ticket reply as of 18 September. The support draft
still says “not submitted”; that is an old drafting status, not verification
of the current ticket. No portal/support inbox or fresh participant state was
queried in this review. The dated local consent renewed through 14 September
23:59:59 IST has elapsed; verify any newer grant before access or transmission.

| Milestone | Implemented / recorded evidence | Not yet completed |
|---|---|---|
| **M1 — ABHA identity** | Backend identity/OTP/enrolment continuation and reception UI exist. Existing-number mobile OTP verification and patient binding have historical live success, most recently documented 13 September. | Full applicable enrolment/verification/profile/card/Scan-and-Share and negative cases. The case ledger has two PARTIAL M1 rows, not two completed cases. Obtain participant input privately and record every applicable case; the missing M2 token callback does not by itself block M1 testing. |
| **M2 — HIP linking/sharing** | Official v3 callbacks/outbound calls, finalized-document contexts, grouped linking, durable jobs, FHIR export and encrypted transfer exist. An earlier token callback succeeded but its link failed/expired. A later request's controlled same-ID retry returned 202; no confirmed link is evidenced. | Resolve the missing genuine callback/link confirmation, then real PHR discovery/link visibility, approved consent, record sharing/notifications and required negative cases. HTTP 202 and synthetic receiver probes are not completed linkage. The alternative MEDIATE user-initiated route needs an approved SMS/HTTPS OTP relay, which the owner has not provisioned. |
| **M3 — HIU consent/exchange** | Consent request/artefact/data APIs, requester snapshots/admin fields, durable transfer handling, encrypted received storage and protected document/PDF viewer exist. Local crypto interoperability and sample bundle validation are recorded. | Genuine or NHA-approved clinician requester details, actual PHR approval/denial, authorized counterparty data, encrypted receive/decrypt/validate/display/receipt, revocation/expiry and evidence. No complete live HIU consent/data exchange is recorded. A synthetic local viewer test is not M3. |

**Supported content is five HI types**, with both lab and imaging represented
under DiagnosticReport: Prescription, DiagnosticReport, OPConsultation,
DischargeSummary and WellnessRecord (`hip/gateway.py::HI_TYPES`). Historical
samples validated against NRCeS 6.5.0 with HL7 validator 6.9.12; that does not
validate every future clinical document or settle current assigned case scope.
The supplied FAQ/workbook conflict on required types remains: confirm with NHA.
ImmunizationRecord, HealthDocumentRecord and InvoiceRecord must have legitimate
source workflows and mappings if in scope; do not generate dummy content.

**Callback diagnostics are built and merged, not a cure proven against NHA.**
Migration 0073 adds durable encrypted/redacted receipts; nginx persists bounded
forwarded-IP claims and receipt IDs in a named log volume. Wrapper-shaped
synthetic probes returned expected 400/404 locally and publicly on 14 September;
isolated receiver tests cover 202 for a matching synthetic operation. Public
receipt read-back/cross-layer correlation and a second recreation-survival
check remain pending in the execution record. `CF-Connecting-IP`/XFF are claims,
not origin authentication; a local probe cannot establish NHA delivery.

Preserve root-level `/api/v3/hip`, `/api/v3/hiu`, `/api/v3/consent` and direct-push
contracts. They do not require the legacy HealthDoc private shared secret.
Keep route-specific headers, freshness/correlation/recipient checks and consent
state gates. Do not add `/api` to the registered bridge base to test a path guess.
Callback-only public ingress can intentionally return 404 for `/`/health; inspect
the actual expected routes, not just the home page. Bridge/services were active
in the last recorded check, not freshly revalidated by this documentation update.

**Resume order:**

1. Close the auth/reception/consent/nursing review findings before declaring the
   next release safe; continue unrelated local work while support is pending.
2. Finish synthetic receipt/log persistence evidence without starting outbound
   workers. Revalidate deployed revision, migration, tunnel and bridge safely.
3. Confirm assigned NHA cases/HI types, consenting participant, current local
   access consent, and genuine/NHA-approved requester metadata. Configure a
   relay only if the selected linking route requires it.
4. Complete applicable M1 browser cases with participant-entered OTPs; never
   reuse an expired credential or infer consent from an earlier chat.
5. Resolve the exact M2 operation using retained receipt/support evidence.
   A same-REQUEST-ID 202 may be deduplication; no extra generation, ID changes,
   quota assumptions or queued-job draining without renewed explicit approval.
6. After confirmed linkage, run scoped real M2/M3 consent/data/receipt paths,
   including denial/revocation/expiry. Keep one finalized document per context.
   Participant grants PHR consent; an agent must not do so on their behalf.
7. Update the case ledger with revision, case/row, safe correlations and actual
   receiver/PHR read-back, then submit the required evidence for NHA assessment.

The general outbound worker was stopped in the last execution record; cleanup
ran separately. Recheck actual runtime/queued work before any start. Never
replace the NHA blocker with invented tokens, clinician identifiers or fixed OTPs.

### Verification performed in this review

| Check | Result / limit |
|---|---|
| `make test-pg p='tests/consent tests/nursing/test_tasks_and_incidents.py'` | **62 passed**, isolated PostgreSQL test database migrated/checked through the existing target; some nursing tests use the suite's SQLite fixture. Initial sandbox Docker access was denied; authorized rerun passed. Not the full backend suite. |
| `cd frontend && npm test` | **112 passed, 0 failed/skipped** on reviewed worktree. No new HD-01/HD-02-specific regression files were added by the implementation commit. |
| `cd frontend && npm run typecheck` | Passed. Not a fresh production build or browser acceptance. |
| Actual consent hook in existing component harness | Reproduced A rows on B's initial render and retained A refresh overwriting B. Synthetic promises/data only; no patient record read. |
| Nurse service with isolated synthetic Order/AsyncMock session | Reproduced cancelled lab → completed and placed lab → completed without a diagnostic result. Service-level proof, not a new live API write or concurrency test. |
| Login return-path check | `//example.invalid/` passes the current guard and resolves off-origin. No external navigation performed. |
| GitHub read-only metadata | #559–#562 merged; #561 four active checks passed, Electron skipped; #563 open at review snapshot. |
| Full suite / all-role browser / current audit / load / NHA round trip | **Not run in this review.** Last recorded full local gate: 1,929 backend + 36 script tests on 14 September, head 0073, with documented warnings. Do not relabel those results as current. |

Detailed sources:
[40-package handoff](Issues/Updates.md), [implementer ledger](Issues/Agent-Change-Log.md),
[ABDM case ledger](docs/abdm-milestone-case-ledger-2026-09-10.md),
[dated live runbook](docs/abdm-m2-m3-next-day-runbook-2026-09-12.md),
[callback evidence](docs/abdm-callback-diagnostics-2026-09-14.md),
[crypto/PDF evidence](docs/abdm-crypto-pdf-cleanup-execution-2026-09-12.md).

---

## Running it

```bash
make setup        # first run, or after pulling realm/seed/dependency changes
make up           # subsequent starts
make down
```

`make setup` MUST end with `Seeded development facility and 15 authenticated
users`. If it stops short, the accounts do not exist and every login fails —
which presents as a wrong password, so people blame themselves before the
script. It now verifies this and exits 1 naming the missing accounts.

App at https://localhost (self-signed cert). All fifteen dev accounts use
`devpass`; usernames and landing routes are in `docs/manual-test-guide.md`.

### Tests

```bash
make test-pg                       # full host gate; real-PG cases + scripts/checks
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

**Billing authority is narrow, and deliberately so.** `billing` and `admin` may
raise, issue and settle an invoice. A pharmacist may do the same *only* for an
invoice made entirely of dispensed medicines — there is one invoice per visit
(§3 0014), so "medicines only" is checked against what is on the invoice, not
against the role. Receptionist and supervisor have no billing access at all;
creating a visit still creates its draft registration invoice server-side
(`opd.service.create_visit`), not patient registration alone. Refunds are admin-approved: the
desk that raises one must not approve it.


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
realm.** Forcing TOTP sends all fourteen dev identities to an OTP enrolment
screen; a strong password policy makes `kc set-password devpass` fail for all
fourteen. Both are correct for production and both live in
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

**A pipe hides the exit code you are reading.** `npm run x 2>&1 | tail -40`
reports `tail`'s status, not the command's. A workflow run with three failures
was read as green because of this. Read the summary line, or drop the pipe.

**A screen that loads is not a screen that works, and the load check cannot
tell you which.** All five defects found in the September role sweep sat behind
screens whose every API call returned 200: a pharmacist's approver search
403ing into an empty list, reception unable to create an IPD or EMERGENCY visit
on a day with no OPD queue, `POST /queue/tokens` accepting any visit id from
any facility, and a "Today's worklist" with no date filter that returned every
token the doctor had ever been issued. Load checks are cheap and catch
wired-to-nothing; only driving the write path catches these.

**`.catch(() => setThings([]))` converts a refusal into an absence.** The
adjustment screen's approver lookup did exactly this, so an admin-only 403
presented as "no colleague by that name works here" — silent, plausible, and
invisible to every gate. If a fetch can fail, the empty state and the failed
state must not render the same.

**A schema field with no rendered input can never be satisfied, and its error
has nowhere to appear.** Three of these were found in one afternoon, and each
one made a whole workflow impossible while looking completely normal.
`AddVitalsForm` required `measured_at`, rendered no control for it and never
set it, so zodResolver rejected every submission and Save Vitals did nothing at
all — no request, no message. `DischargeForm` defaulted
`destination_facility_id` to `""` against `z.string().uuid().optional()`, where
`""` is neither a UUID nor absent, so no patient could be discharged by any
route. If a schema field is required or constrained, either render it or set
it; a field the user cannot see is a field they cannot fix.

**An empty `<input type="number">` reads as NaN, not undefined.** With
`{ valueAsNumber: true }`, every blank optional numeric field reached
`z.number().optional()` as NaN and failed — so a nurse could not record a pulse
without also filling in weight, height and both blood pressures, each rejected
with a bare "Invalid input". Use `setValueAs` and map `""` to `undefined`.

**A native `step` of 1 silently blocks decimals.** `NumberField` set
`inputMode="decimal"` and no `step`, so 37.1 °C was invalid to the browser, the
form never submitted, and nothing in the app said why — constraint validation
reports through a native bubble the page cannot see. The forms now carry
`noValidate` and let zod be the single validation authority, which is also the
only layer that can render a message next to the field.

**`beds.status` is a mirror of `admissions`, and mirrors drift.**
`reconcile_bed_status()` exists to report the disagreement precisely because it
happens. The admission bed picker filtered on the mirror and offered a bed an
active admission already held; the server answered 409 and the screen showed
nothing. Read occupancy from `occupant`, which comes from the admission.

**`token_display` repeats.** It is allocated per department per business day,
so several rows in one list can read `GENMED-002`. Key tests on the patient or
the token id, never on the displayed number.

**A gate that passes vacuously is worse than no gate.** Four of these have now
been found, all reporting success while checking nothing. All four are closed;
they are kept here because the shape recurs.

1. `make contract`'s extractor used `\bapi(?:<[^;\n]*?>)?\(`, whose character
   class excluded every generic containing a `;` or a newline — six real calls
   were invisible while it printed "172 calls match".
2. CI's `PR convention check` ran `pr_check.py` under
   `working-directory: backend`, where every repo-root-relative path from
   `git diff` failed an `exists()` test, so it printed "no python files to
   check" and exited 0 on every pull request it ever ran. `pr_check.py` now
   anchors on `git rev-parse --show-toplevel`.
3. `assert_audit_coverage()` existed and was called from nowhere. It now runs
   in `app.main`'s lifespan with a non-empty `AUDITABLE_MODULE_PREFIXES`.
4. `scripts/tests/` was collected by nothing: `backend/pyproject.toml` pins
   `testpaths = ["tests"]` and `make test-pg` runs pytest from `backend/`, so
   eleven tests guarding the role-evidence report ran in no gate and in no CI
   job. `make test-pg` now runs them too, on a full run.

When a check's output is a number, make something change that number and
confirm the number moves. When a check is a file, confirm something actually
collects it.

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

## Historical implementation notes — 1–12 September 2026

These dated notes preserve earlier rationale and test results. They are not a
current deployment inventory. The 18 September status above takes precedence,
especially for auth safety, migration head, consent expiry, PRs and milestones.

- **12 September crypto/PDF follow-up:** raw X25519 was incompatible with
  Fidelius. The new checksum-pinned BC 1.86 helper supports full Curve25519
  points and X.509 peer keys; known-answer and actual independent CLI exchanges
  pass. Docker/CI build Java runtime; host tests need `make abdm-crypto` with
  JDK 17+ (21 in CI/Docker). Stored keys are format-versioned; never reinterpret
  legacy keys or frozen ciphertext. Embedded PDF intake and canvas-only viewer
  pass synthetic real-browser acceptance including refused-consent refresh.
  Full backend 1816 + 14 script tests, frontend 108/typecheck/build pass.
  Cleanup-only container is running; one-shot cleared zero items. No general
  delivery worker or new NHA clinical request. Current link remains pending,
  participant local consent expired, requester metadata absent. Public health
  404 is expected callback-only ingress; token callback GET 405 and registry
  GET 200 were verified. Tool approval usage limit blocked subsequent probe/log
  inspection. See `docs/abdm-crypto-pdf-cleanup-execution-2026-09-12.md`.

- **ABDM closure branch (9 September)**: `fix/abdm-milestone-closure`
  adds exact finalized-document contexts, transactional publication, per-type HIP
  linking, durable delivery jobs/frozen encrypted transfer pages, protected HIU
  record storage, a read-only `/doctor/abdm` workspace and admin job operations.
  Consent/transfer callbacks now enforce facility scope and monotonic terminal
  states; OTP ownership is checked before the gateway call. PR #537 merged into
  staging with four active CI checks green. Frontend: 34 tests, typecheck,
  production build, 205 contract calls and 49 role/screen entries across 14 roles.
  New ABDM pages have screen-load evidence, not a live milestone round trip.
  Follow-up branch `fix/abdm-historical-registration` replaces the unsafe
  all-facility backfill with explicit, preview-first facility/operator/document
  manifests. It preserves source authors, atomically registers contexts/audits/
  jobs and does not send HTTP. The full gate now passes 1490 backend + 14 script
  tests, including 45 new regressions (three real-PG). See
  `docs/abdm-historical-backfill.md`. No application-data backfill was run.
  Migration 0067 adds committed acknowledgement intents for HIP consent/data and
  HIU consent callbacks, followed by durable transfer/fetch jobs with correlation.
  **The approved local application upgrade 0060 → 0067 passed after backup and
  populated-copy restore/migration: all 121 original tables / 10,912 rows stayed
  identical. Backup retained under ignored `backups/`; disposable clone removed.
  The delivery worker remains stopped. This is not a production rehearsal.**
  The worker override is opt-in and can send queued work when started. Remaining
  M1 continuations, remaining discovery/link/profile reply and callback-timeout
  recovery, approved ingress/registry
  mapping, clinical decisions and live external evidence are explicit in
  `docs/bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md` and
  `docs/abdm-local-verification-and-recovery.md`. Do not use older paragraphs below
  as current proof of certification or deployment.
- 1226 backend tests passing in the 5–6 September retest (four existing ABDM
  Pydantic alias warnings remain); 23 frontend tests and 11 evidence-report
  regressions pass. `pip-audit` and `npm audit` both clean.
  `shadcn` was the root of all three npm advisories (it dragged in express, the
  MCP SDK and babel) and was a **production** dependency that nothing imported:
  the 16 components under `src/components/ui/` are local source, and there is no
  `components.json` for its CLI. Removing it cleared two advisories; the third,
  `browserslist` via `eslint-config-next`, is pinned forward by an `overrides`
  entry in `frontend/package.json`.
- Per-role browser evidence lives in `docs/role-verification-evidence.md`,
  generated by `scripts/build_role_evidence.py` from the three e2e harnesses.
  47 screens across 13 roles and 41 workflow steps in the latest strict run.
  Entries distinguish real writes/read-back from read-only tabs and access
  refusals; they do not prove every button works. All nine workflow groups and
  the superadmin isolation gate passed, with recovery disabled. The report
  rejects incomplete/filtered/mixed runs and failed outcomes, not just failed
  screenshots. `scripts/maintenance/
  discharge_synthetic_admissions.py` frees beds a failed run left occupied.
- **Login rate limiting had a real asset-budget defect.** Keycloak theme
  fonts/JS/images spent the same bucket as credential requests; the retest
  logged 21 refusals, including two login POSTs. `nginx.conf` now excludes only
  GET/HEAD `/auth/resources/` assets from that bucket, retaining the auth
  10r/s + burst-20 policy. A live 40-request asset burst returned 40×200, while
  the same burst against a non-asset auth endpoint still triggered the limit.
- Browser harness traps: `#main-content` exists on authenticated `/` before
  the role redirect finishes; wait for the landing route. Also, navigating the
  login tab can abort its mount-response bodies. Workflow checks now use a
  separate tab in the same real SSO context. Recovery is diagnostic-only
  (`E2E_ALLOW_RECOVERY=1`), never the default release gate.
- **`dev.supervisor2` is the fourteenth account, and it is not padding.**
  THID→UHID promotion is maker-checker: the approver must differ from the
  requester and the unmerger from the approver. With one supervisor the only
  reachable outcome was the refusal, so the approve and unmerge halves of that
  flow had never been executed by anyone.
- The earlier WASA implementation review reported its findings addressed,
  including its finding M3 (not ABDM Milestone 3) — the CSP
  carries a per-request nonce from `frontend/src/proxy.ts` instead of
  `'unsafe-inline'`, and every route renders `force-dynamic` because a nonce
  cannot be baked into prerendered HTML. This is not a current security
  attestation: the new login branch and operational controls need fresh review.
- WASA ABDM track: **M1/M2/M3 are not yet milestone-ready.** The 7 September
  review found public callback HTTP 530/1033, missing OTP-relay configuration,
  incomplete application-initiated linking and no complete HIU clinician
  workflow. See `docs/billing-abdm-readiness-2026-09-06.md` and
  `docs/ABDM-M1-M2-M3-Execution-Requirements-2026-09-07.md` for measured evidence
  and prerequisites; code and sample validation are not a live round trip.
  `hip/gateway.py`
  and `hiu/gateway.py` carry the outbound wire
  protocol (11 calls, every shape taken field-by-field from ABDM's official v3
  Postman collection) and the routers call them. Before this the ten
  `abdm_path_*` settings were referenced nowhere outside `config.py`: the
  package could receive and could not speak, and nothing in the suite noticed,
  because no test fails when a module is simply never called.

  Wired and tested: HIU consent request and health-information request; HIP
  acknowledgements on both callbacks (unacknowledged, the gateway retries and
  then reports the grant failed, so the consent takes effect here and nowhere
  else); HIP care-context notification, whose absence is the classic HIP defect
  — linking works once and every record created afterwards is invisible.

  The official root-level `/api/v3/hip`, `/api/v3/hiu`, `/api/v3/consent` and
  direct transfer callbacks are mounted with nested camel-case contracts. The
  HIP transfer worker selects only consented, confirmed care contexts, builds
  NRCeS document bundles, encrypts and pages the push, then sends the terminal
  transfer notification. Generated OP Consultation, lab and imaging Diagnostic
  Report, Prescription, Discharge Summary and Wellness samples validate with
  zero errors and zero warnings against NRCeS 6.5.0 using the official HL7
  validator 6.9.12. Offline terminology mode emits one informational MIME note
  for the PACS-reference attachment; it is not a warning or error.

  Patient-initiated linking is `MEDIATE`, not `DIRECT`: a random single-use OTP
  is hashed in Redis, expires after ten minutes, locks after five failures and
  is delivered through a deployment-owned HTTPS relay. There is deliberately
  no fixed development OTP. A real M2 run therefore needs
  `ABDM_LINK_OTP_DELIVERY_URL` and its bearer token configured. Remaining work
  includes the product, ingress and durable-recovery gaps in the dated review,
  as well as live M1 verification, M2 discovery/linking and M3 consent/data
  exchange with a consenting sandbox participant. Retain redacted NHA
  milestone screenshots and correlation IDs, never tokens or OTPs.

  `integrations/abdm/consent/` and `nhcx/` remain empty; consent artefact
  handling lives in `hip/` and `hiu/`, and NHCX is out of scope for this audit.
- Earlier frontend hardening removed the `NEXT_PUBLIC_AUTH_MODE=dev` role picker;
  `.env.production.example` carries the `NEXT_PUBLIC_*` build args the image needs.
  Neither fact establishes current production readiness.
- See `docs/wasa-readiness.md` for the full assessment,
  `docs/manual-test-guide.md` for per-role testing, and the Endpoint Atlas for
  every route with its access tier.

### Historical ABDM protocol findings and remaining cautions

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
  their real method. Every old path returned 404. Those probes established
  route existence; the local implementation now covers the corresponding
  request and callback payloads, while real milestone acceptance still needs
  to be captured with a consenting sandbox user.
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

**Official callbacks do not use HealthDoc's private shared secret.** The
published v3 callback requests carry `REQUEST-ID`, `TIMESTAMP` and the addressed
`X-HIP-ID`/`X-HIU-ID`. `X-CM-ID` is route-specific: M2/M3 v2.8 omit it on many
callbacks, while HIU consent on-init requires it. Never infer inbound headers
from outbound calls; see `docs/abdm-callback-header-matrix-2026-09-11.md`.
The published collection does not define a
request-signature header or canonical signing input. The root-level handlers
therefore enforce those headers, UUID/timestamp freshness, replay coalescing,
recipient matching and the durable consent/transaction state machine without
pretending that headers are cryptographic proof of origin. Source restrictions
remain an ingress/Cloudflare control until NHA publishes a verifiable callback
signature scheme. `ABDM_CALLBACK_SHARED_SECRET` protects only legacy private
`/api/v1/abdm/...` callback routes and is not required by ABDM.

**12 September live linking:** Same secret passes session/bridge checks. Fresh
token request `d613360a-99e5-5fc4-873c-b804d01dba8a` completed on 11 September
at 12:40 UTC but has no callback/token as of 12 September 04:19 UTC. The old
dispatch did not retain its exact success HTTP status: job `done` is not proof
of HTTP 202. Do not regenerate (three recorded token job attempts on 11 Sep),
reset the expired original operation, start the general worker or claim M2/M3
passed. Midnight does not prove a rolling quota reset. Local consent **expired
11 September at 23:59 IST** and needs participant renewal before record access.
Owner completed portal login: application approved with M1/M2/M3 requested;
exit/production approval pending. Inspected account/exit pages have no request
trace UI; integrator dashboard is aggregate statistics only. Support draft
not sent. No completion declarations or configuration were changed. Initial
automatic portal snapshot included its plain-text secret; subsequent reads
redacted it, no secret copied to files and no rotation performed.
Token failures/crashes stop after one attempt; explicit lost-callback recovery
permits its existing one extra attempt. Auth/protocol failures are terminal;
non-token transport retries remain. Redirects/non-2xx can no longer count as
success. Token/link, HIU consent/data initiation and receipt require HTTP 202;
HIU receipt success is `RECEIVED`, not HIP's `TRANSFERRED`.

**M3 requester identity is now mandatory and explicit.** Migration 0069 adds
staff registration identifier type/registry URI and consent requester snapshots;
it is applied to local development and test databases, with no fake backfill.
Admin → Users exposes these fields beside registration number. `dev.doctor`
has none configured and cannot request consent until a genuine or NHA-approved
sandbox requester is supplied. Completeness checks are not registry verification.
Legacy missing snapshots fail closed rather than inventing attribution.

**HIP linking groups an explicit selection, not one token per HI type.** Each
document remains a separate context. Mixed-type selection uses one token job
and one grouped POST; exact legacy replays preserve old IDs/counters. A changed
selection cannot reuse the same idempotency key. Do not reset existing pending
work or extend the five-minute local credential-use window to demonstrate it.
Final regression: 1794 backend + 14 script tests pass, head 0069; six existing
Pydantic warnings remain. One earlier DB SSL-setup error did not recur on the
full rerun; no SSL settings or test retries were changed. Frontend: 106
tests/typecheck pass; API contract: 214 calls. Whole-backend lint is not claimed
clean (existing users-module findings persist). See
`docs/abdm-m2-m3-next-day-runbook-2026-09-12.md` for the latest full backend
verification and live execution boundary.

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

**An earlier audit counted 17 of 98 models**, up from 8; this count was not
recomputed on 18 September. `assert_audit_coverage()` is
now called from `app.main`'s lifespan and covers
`app.integrations.abdm.hip` / `.hiu`; removing an opt-in in either package
fails the boot, so the guard is non-vacuous — but it still only guards those
two packages, and the other 81 models are outside its reach. Patient creation is now audited explicitly on
both routes (`POST /patients` and `POST /emergency/patients`) rather than
through the listener, because `update_patient()` already writes its own row and
flipping the opt-in would double-write. Of the 12 models in `app.patients`,
`app.consent` and `app.files`, only three carry a `facility_id` column, and
`audit_logs.facility_id` is NOT NULL — so the other nine need a migration each
before they can opt in. Tracked as #290.

An earlier branch inventory found a `release-readiness` commit containing
`scripts/close_verified_issues.sh`. That is historical, not a current statement
that every other branch is merged. Use the dated PR snapshot above and recheck
remote state before any promotion; teammates' branches are not ours to discard.

---

## Working style that fits this codebase

Comments here explain **why**, especially where the obvious choice is wrong —
OAEP SHA-1/MGF1 SHA-1 because the live ABHA certificate declares that algorithm
(the earlier PKCS#1 v1.5 claim was wrong), `python-jose` removed rather than
upgraded because one CVE has no fix. Keep that. A comment saying what the
line does is noise; one saying why it is not the other thing saves the next
person an hour.

Verify before claiming. Run the audit rather than reading the changelog; parse
the AST rather than grepping; check the ref date rather than trusting the fetch.
Several wrong conclusions here came from a check that confirmed an assumption
instead of testing it.
