# Ten-suite completion review — 20 September 2026

Status: **executing / not fully accepted**. Review target: development and PR
integration into staging, not a production deployment or a certification claim.

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

- Existing working branch: **fix/clinical-safety-keycloak-return**.
- Original Suite 9 workspace: **feat/suite-9-portal-terminology-a11y-m1**, base
  35d8cc4, preserved together with untracked PDFs, Updates.md and backend/uv.lock.
- Suite 9 was already squash-merged to staging as 6505e63 through PR #583.
  The safety branch merges that staging revision without dropping either set
  of changes. No duplicate Suite 9 PR is needed.
- Current integration PR: [#584](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/584),
  **feature branch → staging**. No merge has been performed.
- Main promotion must be **staging → main**, after approval and integration.
  Opening that promotion now would not include the unmerged safety changes.

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
| 8 | HD-29–32 | Immunization, blood crossmatch/issue, forms, CSV, dead-letter and walk-in surfaces. Unsafe issue and payload mismatches repaired; typed form validation added. | Blood release independence, recall/transfusion traceability and adverse-event workflows; approved vaccine schedule; idempotent uncertain write outcomes; form governance/applicability/versioning. Order-set execution remains disabled pending mappings/writer; CSV supports vaccines only, not every advertised entity. |
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
| HD-17 | PostgreSQL nurse contention gate plus approved schedule/dose/correction semantics. Row locking is not a scheduling subsystem. |
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
| HD-29B | Independent screening release, unit/crossmatch/issue/transfusion traceability and recalls; current issue checks are not a complete blood bank. |
| HD-30 | Govern/version forms, transactional idempotent submissions and approved code-mapped order-set writer; complete intended CSV entities. |
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

## Evidence and limits

Commands run from the isolated branch worktree; no production records changed.
Fresh outcome counts and final CI state are maintained in CLAUDE.md / PR #584.

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
