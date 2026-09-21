# HealthDoc implementation review and release conditions — 19 September 2026

> Historical review of revision `542d568`, recovered from `c8dc862` during
> 21 September branch consolidation. Findings and test counts below describe
> that snapshot, not current HEAD. For current status, use [CLAUDE.md](../CLAUDE.md)
> and the [ten-suite ledger](ten-suite-acceptance-status-2026-09-20.md).

## Verdict and review boundary

**Substantial implementation progress; changes required before release.** New
screens and service methods do not yet establish safe, complete journeys.
This is an independent source/targeted-test review, not clinical approval,
a production deployment, an exhaustive security audit or live ABDM acceptance.

- Reviewed immutable application snapshot: `542d568469a91f2135bf2d20757b013e6966c64f`,
  from `feat/suite-8-immunization-blood-forms-walkin`.
- Review work is isolated on `review/project-status-2026-09-19`, in
  `/private/tmp/healthdoc-status-review.b9HyAa`. The developer's original worktree,
  branch, untracked PDFs, `Issues/Updates.md` and `backend/uv.lock` were not changed.
- Local `staging` was `124ff83`: history contains Suite 6 through #577 and
  Suite 7 through #580. Suite 8 consists of `0f6750d` and `542d568` above that
  base. These are **local-history observations**; GitHub's API was unreachable,
  so current remote CI, PR/review status and production deployment are unknown.
- Delta from the earlier review snapshot `1fd429f`: 119 files, 15,718 additions,
  301 deletions. Review concentrated on API contracts, patient/facility isolation,
  clinical/stock transactions, truthful UI outcomes and acceptance evidence.
  Not every changed line or previously existing module was independently audited.
- The branch's `CLAUDE.md` still contained the 18 September status. The earlier
  conversational 19 September update was not present in this snapshot. This
  report and the new leading section restore current, revision-specific status;
  historical notes are retained rather than silently treated as current.

Reference scope is the existing four-PDF handoff at
`/Users/ritikkumar/Desktop/healthdoc/Issues/Updates.md`, not a new re-reading of
all four PDFs. That specification is still untracked in the original worktree.
The tracked [implementer ledger](../Issues/Agent-Change-Log.md) has HD-01–HD-20
entries but has not yet recorded Suite 6–8 package-level acceptance evidence.

## Progress: what exists versus what is accepted

Implementation now touches **HD-01–HD-32**, including two distinct HD-29 modules.
This is **not 32 accepted packages or 80% of the product completed**: packages
have unequal scope and several contain unsafe or nonfunctional paths. The eight
remaining package IDs also include certification and operational acceptance,
not just eight coding tasks. Existing foundations in HD-33–HD-40 remain useful.

| Handoff scope | Source-confirmed progress | Current acceptance condition |
|---|---|---|
| HD-01 | Role-gated post-visit links and honest desk handoff copy | Improved; retain role-by-visit browser regression. |
| HD-02 | Consent labels, synchronous context reset and request sequencing | **Open blocker:** retained old refresh still overwrites a new patient's list. |
| HD-03 | Nursing order row locks; cancelled and diagnostic check-off refusals | Earlier source defects repaired; focused tests pass. Broader race/role acceptance remains. |
| HD-04–05 | Emergency visit/consultation context and no-token recovery queue | Built; populated clinical handoff and recovery acceptance remains. |
| HD-06–09 | Age/address/guardian validation, protected photo, identity cards and exact lookup | Built; complete photo/print/identity and negative acceptance remains. |
| HD-10 | Counter/locale controls and optional desk observations | Partial: desk observations are still not submitted/persisted. |
| HD-11–12 | Appointment CRUD/check-in and stale-visit review/closure UI | **Open blockers:** scope/races/conflict updates and active-encounter closure. |
| HD-13–16 | Dispositions, admission picker/chart and checklist | Built, not fully accepted; approved templates, readmission isolation and concurrent actions remain. |
| HD-17–18 | eMAR writer/corrections and ED triage/board | Dose duplicate guard is not concurrency-safe; clinical schedule/triage approval and action acceptance remain. |
| HD-19–20 | Structured analytes, urgency and medication acknowledgement | New validation rejects missing required values, boolean/NaN/infinity and snapshots analyte versions. Approved effective rules, units and end-to-end fulfilment remain. |
| HD-21 | Durable critical-alert rows, list, acknowledgement, notification row and lab modal | Partial: live delivery remains process-local and happens before commit; replay/retention/escalation acceptance incomplete. |
| HD-22 | Specimen collect/receive/reject/recollect and event history | Partial LIS depth, not a proven analyzer/external LIS integration. QA/QC, mapping, outage and duplicate-message cases remain. |
| HD-23 | Radiology image/PDF attachment API/UI in addition to existing reporting/PACS UID | Upload foundation; no new independent Orthanc/DICOM round trip. Attachment-order correlation needs repair. |
| HD-24 | Pharmacy return UI/API with disposition and ledger entries | **Open blocker:** original issue/lot/facility/quantity/retry/refund reconciliation is incomplete. |
| HD-25 | Invoice care-setting readout, PM-JAY unavailability and refund separation tests | Improvements, not sanctioned scheme integration or complete bed/OT/blood charge accrual. |
| HD-26 | KPI producer/catalogue, receptionist tracker and ED census | **Open blocker:** two published KPI values are fabricated constants; revision/business-date policy incomplete. |
| HD-27–28 | OT scheduling/checklist/operative records and longitudinal program enrolment/visits/exit | Built but scope/concurrency/policy/module-off acceptance incomplete. |
| HD-29A | Vaccine catalogue, schedule, administration and certificate backend/UI | **Not usable as complete:** wire mismatches, wrong-patient access, duplicate/expiry safeguards and approved schedules remain. |
| HD-29B | Donor/unit/crossmatch/issue backend/UI | **Do not use clinically:** unsafe issue demonstrated; UI contract, isolation and traceability also incomplete. |
| HD-30 | Dynamic forms, order-set preview/apply and CSV UI/API | Partial: order-set/unsupported CSV success is not persistence; forms validation/context safety incomplete. |
| HD-31 | Generic integration console, metrics and dead-letter/replay endpoints | Partial: actual dead-letter production, safe replay and tenant/PHI controls incomplete. Existing ABDM job console is separate and must be preserved. |
| HD-32 | `direct_service` enum/model/type label, exempt from bed and OPD token categories | Foundation only; test inserts a Visit directly, not an identity → order → bill → fulfilment journey. |
| HD-33–34 | Existing bound portal and terminology foundations | No new closure evidence in this delta; released-document policy/flows and governed terminology still pending. |
| HD-35 | Existing UI/print/accessibility foundations | New screens introduce contract/context/error-state gaps; refreshed keyboard, print and action acceptance needed. |
| HD-36–37 | Existing ABDM identity/HIP/HIU framework | M1 partial; M2/M3 live acceptance unproven. See milestone conditions below. |
| HD-38 | Existing recovery/security/observability tooling | Production-derived restore/PITR, receiver delivery, clinical load/security and named approvals remain unproven here. |
| HD-39–40 | Existing referral/tariff/switch tests and role smoke harnesses | Fresh populated actions/read-back, negative cases and latest-SHA release evidence remain; dashboard mounts alone cannot close these. |

## Findings and required repairs

### R1 — Blocker: patient/facility ownership is not enforced on new routes

`immunization/router.py::get_patient_immunization_schedule` and
`forms/router.py::list_patient_form_submissions` read
`_ = current_user.facility_id` but pass only the caller-supplied patient ID to
unscoped services. Both admit the `patient` role without verified self-binding.
Certificate lookup and record/submission writes also lack the needed ownership
checks. Blood donor/unit queries are global; their tables do not model facility
ownership. OT/program create services and pharmacy returns do not validate all
supplied patient/visit/admission/lot IDs against the caller's facility.

**Reproduced:** with the real routers, a synthetic authenticated patient-role
actor from a different facility and no self-binding received another patient's
immunization schedule and form submissions, both HTTP 200. Authentication was
dependency-overridden; actual resource queries used the isolated SQLite fixture.
This tests resource authorization, not JWT verification or a real user account.

**Fix/accept:** centralized staff resource scoping; use existing verified
self-patient binding for patient access; scope every joined parent and related
ID, not merely the newly created row. Model blood ownership explicitly. Add
real HTTP wrong-patient/wrong-facility tests returning the established 404/refusal
contract. The existing AST checks pass despite these defects: mentioning
`facility_id` is not proof that it constrained a query.

### R2 — Blocker: blood release accepts unsafe unit states

`blood_bank/service.py::issue_blood` checks crossmatch compatibility and whether
the unit is already issued, but not expiry, screening success or an available
state. `create_unit` accepts an ineligible donor; screening defaults to passed.
Issue uses no row lock/conditional transition to prevent concurrent release.

**Reproduced:** an expired unit from an ineligible synthetic donor, with failed
screening and `quarantined` status, was crossmatched and issued successfully.

**Fix/accept:** keep clinical use disabled until approved collection/screening/
release rules, explicit authorization and immutable traceability are enforced.
Lock the unit and crossmatch; require an eligible state and approved screening,
expiry and patient/unit correlation. Prove quarantined/expired/failed/cancelled
refusal, independent release where policy requires it, retries and two-user
contention against PostgreSQL. Do not invent clinical compatibility rules.

### R3 — Blocker: new frontend and backend contracts disagree

There is no translation in `features/immunization/api.ts` or `blood-bank/api.ts`:
they send/return the declared TS object directly.

| Workflow | Frontend expects/sends | Backend actually requires/returns | Consequence |
|---|---|---|---|
| Immunization schedule | `records`, `due_vaccines`, `overdue_vaccines` | `administered`, `due` | Actual component throws reading `schedule.records.length`. |
| Record vaccination | `vaccine_id`, `administered_date` | required `vaccine_code`, optional `administered_at` | Required-field validation fails; intended date is not mapped. |
| Certificate | nested `patient`, `vaccinations`, `digital_signature_hash` | flat patient fields and `records`, no such signature | Render contract is invalid; do not fabricate a signature. |
| Blood unit create | `unit_number` | required `bag_number` | Validation failure. |
| Blood crossmatch | `blood_unit_id` | required `unit_id` | Validation failure. |
| Donor create | `age`, `gender`, `contact_phone`, UI eligibility | `age_years`, `sex`, `mobile`, measured eligibility inputs | Extra fields can be silently ignored; intended information is lost. |

**Reproduced:** actual schedule TSX crashes with the backend response shape;
three representative outgoing UI payloads fail the actual Pydantic models on
`vaccine_code`, `bag_number` and `unit_id` respectively.

**Fix/accept:** one explicit generated/validated wire contract or tested adapter;
real populated browser create/read-back/certificate/print flows. Add request
and response-shape tests, not just route existence or handwritten TS types.

### R4 — Blocker: successful actions that do not do the claimed work

- `forms/service.py::apply_order_set` validates that a patient and visit exist,
  then returns `orders_applied` and a success message without creating orders.
  It does not validate that the visit belongs to that patient. The UI also
  passes `visitId={activePatient.id}`, so normal UI usage has no real visit ID.
- `import_csv` imports vaccines only; other entity types return the input row
  count as successful imports without writes. These include advertised forms
  and inventory imports. Dry-run validation does not establish schema/reference
  validity or reliable per-row failure handling.

**Reproduced:** applying a populated set returned success with order count
unchanged at zero; an inventory CSV returned `imported_count=1` without an
inventory write path.

**Fix/accept:** disable unsupported actions with an honest reason, or connect
them to authorized transactional domain services. Select a real patient visit;
require explicit approved order confirmation and stable codes. Persist/read
back every claimed row; refuse unsupported CSV entity types; validate bounds,
types, references and duplicates before committing, with row-level errors.

### R5 — High: immunization/form validation and clinical governance incomplete

`immunization/service.py` auto-seeds a hardcoded catalogue on read. The due-list
calculation ignores `max_age_days`, and administration lacks duplicate dose,
expiry-at-administration, inactive-vaccine and validated schedule safeguards.
`forms/service.py` auto-publishes hardcoded clinical forms/order sets; submissions
check field presence, not declared types, select options, bounds, publication
status or visit ownership. No named clinical approval is evidenced for these
defaults. This is a governance gap, not a recommendation for replacement rules.

**Fix/accept:** approved, versioned definitions; explicitly governed activation;
typed immutable form submissions; authorized historical-dose/correction flows;
patient/batch/dose identity and idempotent writers. Test invalid types, retired
definitions, repeated requests and preservation of historical versions.

### R6 — High: executive metrics publish made-up measurements

`reports/service.py` sets OPD average wait to `14.5` whenever an OPD visit exists
and laboratory TAT to `2.40` regardless of laboratory source rows. Snapshots are
overwritten in place on subsequent production. Date windows use UTC, not the
facility's business timezone; historical bed occupancy uses current occupancy.

**Reproduced:** a synthetic facility with no laboratory results published
`LAB_TURNAROUND_HOURS=2.4`.

**Fix/accept:** calculate from authoritative timestamps and explicit denominator,
or publish unavailable/not-computed, never a plausible constant. Define metric
owners, timezone, period closure and correction versions. Reconcile known source
rows, zero-data periods, midnight boundaries and late amendments.

### R7 — High: pharmacy returns are not reconciled to the original issue

`pharmacy/service.py::create_pharmacy_return` checks existence of patient/item/
batch separately, not facility, batch-item identity, original dispense ownership
or remaining returnable quantity. Selecting `resalable` directly increments
stock; there is no independent approval, expiry check or request-idempotency
guard in the new route. Quarantine writes a negative write-off while leaving
batch availability unchanged, requiring explicit reconciliation of ledger
semantics. There is no refund/credit linkage in this writer.

**Fix/accept:** validated original dispense-line/lot references; facility scope,
cumulative-return caps and locking; approved inspection/disposition; stable
idempotency; ledger and refund/credit read-back. Prove repeats and concurrent
partial returns cannot manufacture stock or credit. Existing happy-path tests
do not assert these properties.

### R8 — High: durable alert rows are not durable live delivery

`pathology/router.py::_publish_critical_alert` now persists alert and notification
rows, which is real progress. However, it still enqueues SSE directly before
the result transaction commits. Streams use process-local queues without a
cross-process consumer/replay cursor. The list endpoint returns newest rows
and a newest-timestamp cursor with `>` filtering: it is not a complete backlog
pagination scheme when the initial backlog exceeds the limit.

**Fix/accept:** transactional outbox/committed event delivery, deterministic
cursor/tie-breaker, authorized reconnect/replay, durable acknowledgement and
approved escalation. Test rollback, separate writer/reader processes, >limit
backlogs, restart and one-time acknowledgement. Do not describe the current SSE
as guaranteed critical notification.

### R9 — High: generic outbox console/replay is not complete or safe yet

The existing shipper marks `outbox_events.status='dead_letter'`; it does not
populate the new `outbox_dead_letter` table consumed by the new console.
`replay_dead_letter` creates a fresh event UUID from the **redacted** payload,
sets sensitivity to normal and lacks facility/replay/consent correlation policy.
`redact_payload` does not descend into arrays or cover general patient/clinical
fields. Metadata/dead-letter reads have no facility predicate. Event-list DTOs
omit payloads, but the dead-letter DTO exposes `payload_redacted` directly.

**Reproduced:** a token nested in an entries array and a patient-name key survive
the redaction helper. No outbound worker was started during this review.

**Fix/accept:** wire actual exhaustion to one durable dead-letter source; retain
encrypted authoritative payload/reference separate from display redaction;
preserve original correlation/idempotency and sensitivity on authorized replay;
enforce scope, consent/expiry and nonreplayable states. Test the real worker
failure → console → safe retry path, not manually seeded DLQ rows. Legacy FHIR
plaintext outbox producers also remain unchanged by this delta.

### R10 — High: new patient screens repeat stale-context and misleading-error patterns

Forms and immunization auto-select the first patient returned for literal
`"Demo"`; searches select the first match without confirmation and advertise
UHID lookup while nonnumeric text is sent as `full_name`. Search/no-match errors
can leave the previous patient active. Forms history and immunization requests
lack request-generation/context validation; forms errors become an empty list.
Several controls remain visible for roles that cannot execute their backend
actions (for example CSV administration in the shared forms page).

**Fix/accept:** no implicit default patient; explicit, confirmed result selection;
real UHID lookup; synchronous context reset, keyed forms/modals and cancellation/
generation guards; distinct error versus empty states; capability-gated actions.
Test delayed A responses, B selection, failed search, certificate/modal state,
refresh/logout and role-specific write attempts.

### R11 — High: OT/program scheduling is not proven race-safe or fully scoped

OT conflict detection is a SELECT then INSERT without exclusion/locking; patient,
visit and admission associations are not validated against each other/facility.
Program enrolment similarly checks before insertion; the ORM index named
`uq_active_program_enrolment` is not unique, although **migration 0078 does add
a partial unique index for active enrolments**. Credit that PostgreSQL safeguard;
the SQLite fixture does not exercise it, and concurrent conflict handling still
needs verification. Missing program definitions fall back to the supplied code;
active status is not checked. Program defaults/follow-up rules need
approval. OT and blood routes also need the documented module-off enforcement;
immunization was made core/default-on without evidence of a launch decision.

**Fix/accept:** transaction-safe resource allocation, scoped parent relationships,
active approved definitions, guarded module enablement and versioned clinical
history. Use concurrent PostgreSQL tests and HTTP negative tests; sequential
duplicate tests do not establish race protection.

### R12 — High: radiology attachment fallback needs stricter correlation

`radiology/router.py::upload_order_attachment` scopes the order but accepts an
optional radiology item ID without establishing that the item belongs to that
order/patient. It does not require the order to be radiology. MIME detection can
fall back to caller-supplied content type and object-storage exceptions are
echoed in the response. Storage is tested with a mock in the new Suite 6 tests.

**Fix/accept:** validate order type and item/order/patient relationship, approved
content validation and bounded streaming, safe error messages, expiry/revocation
and orphan-upload recovery. Prove real MinIO upload/read-back and the separately
scoped Orthanc/DICOM journey; the fallback alone is not PACS integration.

## Earlier safety findings: do not lose them between branches

These source paths are unchanged between `1fd429f` and this snapshot:

- **Consent:** `useConsentRecords` compares two values from the same captured
  filters. A retained A refresh increments the current request counter and can
  replace B's loaded rows. Reproduced again with the actual hook harness.
- **Dose concurrency:** `nursing/service.py::record_administration` uses
  SELECT-before-INSERT; no stable dose uniqueness/locking is added here.
- **Appointments:** ownership validation, overlap updates, duration-only end
  recalculation, terminal check-in and concurrency still need repair.
- **Stale visits:** `Facility.timezone` enters the candidate query without a
  facility join; closure ignores `has_active_encounter` and does not lock/recheck
  clinical state. The supplied closure reason is not recorded by the service.
- **Desk observations:** StartVisit fields are rendered but absent from the
  submitted visit/token payload. Do not imply they were recorded.
- **Authentication:** direct password grant and script-readable refresh-token
  persistence in session/local storage remain; production MFA/required actions,
  SDK refresh bookkeeping, rotation/revocation and expiry need acceptance.
  The previous protocol-relative return-path bug was fixed; do not re-report
  that old version as current.

Credit a real closure: the previous configured-analyte missing-all-fields,
boolean and nonfinite-number defects have been repaired in Suite 6. Latest
version selection and version snapshots are present. This does not validate
clinical thresholds, loose name/unit aliasing or the remaining legacy fallback.

## ABDM M1/M2/M3 conditions

No ABDM integration source or milestone evidence document changed in the reviewed
delta. Adding immunization source tables **does not add an ImmunizationRecord FHIR
export or complete a new HI type**. The existing supported set remains the five
types recorded in the dated runbook; applicable NHA scope still needs resolution.

| Milestone | Current evidence-based status | What changes the status |
|---|---|---|
| M1 | Identity APIs/UI and historical existing-number OTP/binding evidence; two PARTIAL ledger cases, not full acceptance | Applicable enrolment/verification/profile/card/Scan-and-Share and negative cases executed with participant-entered OTPs and saved evidence. |
| M2 | HIP callbacks/jobs/export exist; earlier expired link and later unconfirmed operation; no new confirmed live link here | Genuine correlated callback/link confirmation, PHR visibility, valid approved consent and real sharing/receipt plus failure cases. MEDIATE requires the still-unprovisioned approved OTP relay. |
| M3 | HIU consent/receive/crypto/protected-viewer foundations; no completed live exchange recorded | Genuine/NHA-approved requester identity, participant PHR grant/denial, authorized counterparty, receive/decrypt/validate/view/receipt and revoke/expiry cases. |

Owner's last report was that support had not replied; no ticket portal/inbox was
checked now. Historical local consent through 14 September has elapsed; verify
current grant before any participant access/transmission. This review neither
requested OTPs/tokens nor started workers, drained queues, edited bridge URLs
or sent clinical data. Synthetic checks are not NHA-origin evidence/certification.

## Verification actually performed

All application checks below target `542d568`, not a moving developer worktree.
Existing local Python/Node dependencies were reused; frontend dependencies were
symlinked read-only by convention into the isolated worktree. No dependency
installation, source fix, deployment or production data write was performed.

| Check | Actual result and limit |
|---|---|
| Three new suite test files | **23 passed**: `test_suite_6_alerts_lis_pacs_returns.py`, `test_suite_7_billing_kpi_ot_programs.py`, `test_suite_8_immunization_blood_forms.py`. Shared in-memory SQLite fixtures; storage mocked where specified. |
| Earlier safety/scope tests | **111 passed** across facility AST/role tests and nursing tasks, appointments, stale visits, dispositions, eMAR/triage, patient input, queue listing and patient search. Not the full backend suite. |
| `npm test` | **117 passed, 0 failed/skipped**. No new acceptance implied for Suite 8 contracts. |
| `npm run typecheck` | Passed. Handwritten TS interfaces can agree with themselves while disagreeing with JSON. |
| Migration integrity checker | Passed: **86 migrations, linear chain, head 0079**. Static check only, not a migrated/restore-tested database. |
| API route contract checker with explicit `--frontend frontend/src` | **303 calls matched**. Checks paths/methods, not payload/response/role/clinical semantics. |
| Negative synthetic probes | **Seven defect probes reproduced** foreign-patient reads, unsafe blood issue, phantom order-set/CSV success, invalid UI payload shapes, redaction gaps, fake TAT and SSE delivery surviving rollback. Passing a defect probe confirms a defect, not safety. |
| Actual TS/TSX component harness | Immunization schedule render failure and retained-consent-refresh cross-patient overwrite reproduced. No browser/Keycloak acceptance claimed. |
| `make test-pg` | **Blocked before tests**, exit 69: Xcode licence not accepted on this Mac. Owner must review/accept the licence; reviewer did not accept legal terms. SQLite does not replace PostgreSQL migration/locking tests. |
| GitHub read-only PR metadata | API connection failed; current remote PR/CI status not verified. |
| Live all-role browser, PostgreSQL race/load, new production build, MinIO/PACS, NHA round trip | **Not run** in this documentation review. |

Harness corrections were explicit: the first standalone contract invocation had
an import-path error, then a wrong default frontend path reported zero calls;
neither counted as a pass. The corrected explicit-path run found 303. Temporary
probe collection needed `PYTHONPATH=.:tests`; the added SSE rollback probe initially
omitted required `sample_type` and failed during setup, not in the application.
After correcting the synthetic fixture, all seven probes reproduced the stated
defects. These initial errors are reviewer setup errors, not product failures.

## Conditions to close this review / next delivery order

1. **Contain unsafe exposure:** keep affected blood/immunization/form/order-set
   operations out of clinical use until R1–R5 are repaired; do not broaden roles
   or relax failing tests to make the screens appear usable.
2. **Restore honest data:** fix wire contracts, explicit patient/visit selection,
   false order/import success and fabricated KPI values; test persisted read-back.
3. **Protect transactions:** returns, dose identity, appointments/OT/program races,
   stale-visit closure, alert commit/replay and outbox correlation/redaction.
4. **Obtain actual approvals:** clinical/lab/pharmacy/blood/finance/privacy owners
   approve applicable rules, defaults, release and retention before activation.
5. **Verify deployment:** migration 0079 on a safe PostgreSQL rehearsal, scoped
   API negative tests, real role actions, faults/retries, keyboard/print and
   populated UI on the exact build. Resolve the local Xcode prerequisite first.
6. **Update the implementer ledger:** each HD item needs final SHA, commands,
   environment, screenshots/read-back, negative cases, policy approval and an
   independent verdict. HD-21–HD-32 need entries, not only commit titles.
7. **Promotion only after review:** fresh latest-SHA CI and approval into staging;
   staging → main under the existing policy. No promotion is approved by this
   review, and no direct feature-branch → main change is authorized.
8. **ABDM remains a separate acceptance track:** resume only with current
   participant/consent/requester prerequisites and controlled operation evidence.
   Module completion or a green local test count cannot confer certification.
