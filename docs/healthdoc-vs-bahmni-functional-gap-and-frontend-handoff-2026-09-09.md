# HealthDoc vs Bahmni — functional gaps and implementation handoff

**Reviewed:** 9 September 2026. **HealthDoc source:** `151f6c754868ba8ef9adde699f6d2acb8c50c716`.
**Reference roots:** `/Users/ritikkumar/Desktop/BahmniIndiaDistro` and
`/Users/ritikkumar/Desktop/Bahmni`.

**Implementation follow-up:** initial F01/F05 fixes are on
`fix/billing-tariffs-patient-safety`; see
[changes, verification and deployment requirements](billing-patient-safety-fixes-2026-09-09.md).
The original findings below describe the reviewed baseline. The later
[F02 tariff-management implementation](tariff-management-2026-09-09.md) adds the
catalogue UI and real workflow checks; deployment, approved configuration and
server concurrent-revision/replay hardening remain explicit. Other work packages
and ABDM certification are not closed by these changes.
The subsequent [local browser acceptance report](billing-patient-safety-browser-acceptance-2026-09-09.md)
records the tested paths and remaining limits. The original fixes merged into
staging in PR #541; invoice-switch follow-up is PR #543. Tariff work is submitted
for staging review on `feat/billing-tariff-management`, not deployed to production.

## 1. Read this first

This is the consolidated engineering handoff for completing HealthDoc's known
functional gaps, including frontend work. It supersedes outdated “missing”
claims in the 7–8 September comparison reports, but does not replace their
historical evidence.

**Do not rebuild what is already working. Do not copy Bahmni's older ABDM wire
protocol. Keep HealthDoc's Next.js/FastAPI/Keycloak architecture and visual identity.**
Use Bahmni to understand complete workflows, not as proof that a cloned
component is compatible, safe or already certified for HealthDoc.

This review inventoried all **23 local reference repositories**, traced selected
source paths, reviewed current HealthDoc services/screens and checked GitHub.
It did **not** start Bahmni, execute every HealthDoc button, run a live ABDM
exchange or establish full feature parity. “Everything” below means all
identified work packages within this comparison; it is not a guarantee that
there are no undiscovered defects. Runtime-dependent claims are explicitly
separated from source-confirmed gaps.

### Current integration and test baseline

- [PR #537](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/537) is merged
  into staging. Its four active CI checks passed.
- [PR #539](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/539), the
  historical-document registration follow-up, is **also now merged into
  staging**, with four active checks successful. Electron packaging was skipped
  by the workflow, not tested by those results.
- Last full local gate: **1,490 backend tests + 14 script tests passed**,
  four existing Pydantic alias warnings; **74 migrations, linear head 0067**.
  The 45 new historical-registration regressions include three real PostgreSQL
  tests. The backend suite combines SQLite and PostgreSQL tests.
- Previous frontend gate: **34 tests**, typecheck/build passed; last contract
  check matched **205 API calls**. Path matching does not prove response shapes.
- Hosted dashboard gate covers **49 role/screen entries across 14 roles**.
  Screen loads are not complete workflows; the new doctor ABDM page is
  deliberately lazy until a patient is selected.
- The approved local application upgrade 0060 → 0067 was rehearsed on a
  populated disposable copy: 121 original tables / 10,912 rows matched after
  restore and upgrade. This is **not** a production or full disaster-recovery
  rehearsal.
- No historical application-data manifest was applied; no delivery worker was
  started in that implementation work. No milestone approval is inferred from
  a branch merge. Production deployment/main parity was not established here.

### Evidence labels

| Label | Meaning |
|---|---|
| **Implemented** | Relevant source path exists; preserve it. Tests establish only their stated cases. |
| **Confirmed gap** | Source shows a missing caller, unfinished state transition, stub or incompatible contract. |
| **Confirmed source defect** | The inspected active implementation contradicts its intended behavior. Browser reproduction may still be required. |
| **Verification gap** | Implementation exists; an end-to-end or deployment outcome is not yet demonstrated. Do not call it broken without reproduction. |
| **Scope decision** | A broader Bahmni capability has no established HealthDoc equivalent; business/clinical approval is needed before building it. |
| **External dependency** | Requires NHA, an authorized participant, clinical governance, operational approval or a third-party system. |

Priority: **P0** = potential wrong-patient, wrong-money, inappropriate disclosure
or milestone-blocking behavior; **P1** = incomplete core workflow; **P2** =
broader product depth or quality; **P3** = optional scope expansion.
These are engineering priorities, not clinical risk assessments or legal findings.

### Navigation and first assignments

- [Immediate functional defects: F01–F05](#3-work-packages--immediate-functional-defects)
- [ABDM completion: A01–A12](#4-abdm-completion-packages)
- [Hospital workflows: H01–H12](#5-core-hospital-functionality-beyond-abdm)
- [Frontend rules and assignment board](#6-shared-frontend-implementation-rules)
- [Operational and release work: O01–O03](#7-operational-and-release-work)
- [Role/action tests and definition of done](#8-test-matrix-and-done-definition)
- [Sequence, effort ranges and required decisions](#9-implementation-order-and-realistic-planning)
- [Developer ticket template](#10-tickethandoff-template-for-another-developer-or-coding-agent)

Start with the **F01 tariff path**, **F05 patient-switch state** and **A09 legacy
clinical outbox** source findings. Assign **A08/A12 external prerequisites** at
the same time. F03 eMAR needs a clinically approved dose-identity policy before
exposing the write action. This sequence is not a claim that every P0 is already
reproduced in the deployed browser.

## 2. What the comparison actually means

Bahmni's public feature list describes registration, clinical records/forms,
laboratory, inpatient care, stock, billing and reporting. Treat it as the scope
catalogue, not execution evidence. [Official feature list](https://www.bahmni.org/feature-list)

| System | Composition and useful lesson | Do not assume |
|---|---|---|
| Bahmni main distribution | OpenMRS clinical system; OpenELIS lab; Odoo stock/accounting; PACS integration; reporting; old and new clinical frontends. Study the handoff between ordering, fulfilment, results and money. | All source HEADs are the same packaged release, or all optional components are enabled. |
| Bahmni India distribution | ABHA UI, HIP service, clinical-to-FHIR adapter, encounter-event listener, HIU service and clinician UI. Study complete identity → sharing → receiving lifecycles. | This is a drop-in plugin for HealthDoc or today's v3-compatible certification package. |
| HealthDoc | One modular FastAPI/Next.js product, PostgreSQL domain model, Keycloak identity, dedicated ABDM jobs, Redis/MongoDB/MinIO support. | A smaller system boundary means equal feature depth, or a dashboard equals a completed clinical workflow. |

The local India HIP constants explicitly use `v0.5`, `v1.0` and ABHA `v2`;
the HIU constants use `/v0.5`. HealthDoc's new work must follow the current
assigned v3 contract and supplied collections, not those old endpoint strings.
The current NHA documentation URL returned HTTP 403 to this review, so the
assigned checklist, mandatory branches and assessment conditions were **not**
freshly verified. Obtain them through the authenticated portal/NHA contact.

### Reference index used below

All paths are relative to the indicated local root. The directories are research
references; no source was copied and no changes were made in them.

| ID | Reference source | What to learn |
|---|---|---|
| B01 | India: `ABHA-Verification/src/components/creation/` — `VerifyMobile.jsx`, `CreateABHAAddress.jsx`, `LinkABHAAddress.jsx`, `ABHACard.jsx` | Separate identity steps and actionable intermediate states. |
| B02 | India: `ABHA-Verification/src/components/patient-details/patientDetails.jsx`; `ABHA-Verification/src/api/hipServiceApi.js` | Returning verified identity to the hospital workflow. Do not copy wildcard parent-origin handoff. |
| B03 | India: `hip-atomfeed-listener/hip-atomfeed/src/main/java/org/bahmni/module/hipfeedintegration/` | Encounter processing, explicit event initiation, new-context handling. |
| B04 | India: `openmrs-module-hip/api/src/main/java/org/bahmni/module/hip/builder/` | Type-specific clinical FHIR mapping, not a generic report blob. |
| B05 | India: `hip-service/src/In.ProjectEKA.HipService/DataFlow/` | Queued transfer orchestration. Independently validate acknowledgement/retry safety. |
| B06 | India: `health-information-user/src/main/java/in/org/projecteka/hiu/` | Consent requests, callback correlation, record retrieval. |
| B07 | India: `hiu-ui/src/components/HealthInformation/HealthInformationContent.view.js`; `hiu-ui/src/pages/PatientHealthInformation/` | Clinical views for observations, reports, conditions, medications and documents. |
| B08 | Main: `bahmni-apps-frontend/apps/clinical/src/components/forms/`; `bahmni-apps-frontend/apps/clinical/src/hooks/useObservationFormData.ts`; `standard-config/` | Configurable clinical controls, form definitions, encounter-type/privilege gating. |
| B09 | Main: `bahmni-apps-frontend/apps/appointments/` | Booking and unavailable-time UI; distinct from today's OPD queue. |
| B10 | Main: `openmrs-module-ipd-frontend/src/features/DisplayControls/DrugChart/`; `openmrs-module-ipd-frontend/src/features/CareViewPatientsSummary/`; `openmrs-module-ipd/` | Nursing medication/care workspaces and longitudinal shift visibility. |
| B11 | Main: `OpenElis/openelis/src/us/mn/state/health/lims/`, especially `referral/` | Sample/result/referral lifecycle and specialized lab system depth. |
| B12 | Main: `bahmni-odoo-modules/bahmni_stock/models/stock_picking.py`; `bahmni-odoo-modules/bahmni_account/`; `bahmni-odoo-modules/community_modules/` | Batch movements, validation, prices and accounting integration. Not portable FastAPI code. |
| B13 | Main: `bahmni-reports/src/main/java/org/bahmni/reports/report/`; `bahmni-reports/src/main/resources/sql/` | Actual report definitions, inputs, calculations and templates. |
| B14 | Main: `pacs-integration/package/`, including DCM4CHEE and OHIF configuration | Orders, image archive/viewer topology and separate image infrastructure. |
| B15 | Main: `bahmni-apps-frontend/apps/patient-documents/src/` | Visit-scoped upload/list/view experience. This is not proof of a patient self-service portal. |
| B16 | Main: `bahmni-module-immunization/`; India B04 immunization builder | Immunization as clinical source data plus a dedicated export mapping. |
| B17 | Main: `bahmni-docker/bahmni-standard/`; India: `bahmni-india-package/docker-compose.yml` | Deployment boundaries, dependencies, backup surface, operational isolation. |

### Fixed findings that must not be reopened as “missing”

| Earlier finding | Current source/evidence |
|---|---|
| No pharmacy dispense API | `backend/app/pharmacy/router.py` and API-connected pharmacy screens exist. Remaining action/approval tests are below. |
| No external-results backend | `orders/router.py` has POST/GET external-results; service persists results and completes referred orders. Frontend intake remains missing. |
| Lab alerts doctor-only | `CriticalAlertListener.tsx` allows doctor and lab_tech; backend routes facility lab and ordering-doctor alerts. Reliability/clinical-rule gaps remain. |
| Radiology title-only / no cancel-reschedule | Real worklist/report UI and `schedule`, `reschedule`, `cancel`, `scan-complete`, `sign-off` APIs exist. |
| No HOD roster creator | `features/hod/RosterManager.tsx` exists. Re-test production-like setup without demo seed rather than rebuilding it. |
| No procurement/DPDP/maintenance UI | `features/inventory/`, `features/dpdp/DpdpGovernance.tsx`, `features/maintenance/MaintenanceLogPanel.tsx` exist. |
| Patient portal has no binding implementation | Verified binding and a privacy dashboard exist. Unbound access correctly refuses; clinical-document self-service is a separate gap. |
| Reports is only ping | KPI snapshot read APIs and MIS frontend exist. The missing part is the KPI producer, not the reader. |
| HIP transfer worker and HIU viewer absent | Both exist, with exact scope, durable jobs, encrypted received storage and a read-only viewer. Completion/recovery/clinical presentation remain. |
| All old fixture importers remain | Current search did not find active `@/lib/data` importers. Do not repeat the old 15/29 counts; separately audit static business rules and dormant code. |
| Every role sees every menu / superadmin must behave like admin | Sidebar/route/role tests exist. Preserve platform-versus-facility separation; superadmin must not inherit unrestricted clinical access. |

### Traceability to the earlier ABDM report

The original G1–G13 descriptions are historical; use that report's dated update
and the current packages below instead of treating its old defect text as open.

| Earlier gap | Current disposition and remaining package |
|---|---|
| G1: discarded request range | Scope is persisted and enforced; deployment/negative live proof remains in A08/A10/A12. |
| G2/G3: visit-wide export, missing automatic producers | Exact-document exporters/producers and historical tool exist; A05 clinical versions/validation and A11 approved execution remain. |
| G4: unused HIP linking and mixed-type correlation | Staff linking and separate token/link correlation exist; A01 fixes the separate M1 account-credential purpose; A06/A12 cover recovery and live link proof. |
| G5: no durable transfer jobs | Leased jobs and persisted pages exist; A06 covers remaining inline replies and missing asynchronous outcomes. |
| G6/G7: unsafe received storage/content binding | Protected HIU store and strict checks exist; A05/A10 cover validation/interoperability. A09 corrects the overbroad earlier “no new plaintext outbox writes” wording: legacy OPD/discharge producers still write clinical payloads. |
| G8: incomplete revocation cleanup | Partial/expiry cleanup exists; A10/O01 cover worker operation, races and restore proof. |
| G9: no doctor HIU workflow | Request/link/view screens exist; A07 adds clinical presentation and A12 proves the real browser round trip. |
| G10: ingress and facility mapping | A08 remains an explicit deployment/external requirement. |
| G11: incomplete M1 branches | A01–A04 cover account purpose, mobile, address/card and real Scan-and-Share tickets. |
| G12: patient-initiated link OTP delivery | Adapter exists; A12's OTP prerequisite below requires configured authorized delivery and actual PHR proof. |
| G13: clinical/external evidence | A05/A12 plus O01/O02; tests and CI do not substitute for assigned assessment evidence. |

## 3. Work packages — immediate functional defects

Each package below states what exists, what is missing, files to change,
frontend requirements and acceptance evidence. New endpoint/table names are
design suggestions until reviewed; existing paths are explicitly identified.
Estimates later are planning ranges, not completion promises.

**Path convention:** abbreviated frontend paths start at `frontend/src/`;
ordinary backend module paths start at `backend/app/`. ABDM submodule paths
such as `identity/service.py` start at `backend/app/integrations/abdm/`.
Staff API paths omit the common `/api/v1` prefix. Official ABDM `/api/v3/...`
callback paths are a separate contract; do not derive them from staff routes.

### F01 — Automatic departmental billing uses static tariffs [P0; confirmed source defect]

**Evidence:** `backend/app/billing/service.py::_aggregate_lab_charges` calls
`price_lab_test`; `_aggregate_radiology_charges` calls
`price_radiology_modality`. Both use static dictionaries in
`backend/app/billing/pricing.py`. A real effective-dated `charge_master` and
lookup logic already exist elsewhere in the service. The automatic
`_insert_line_idempotent` path does not pin a tariff ID.

**Effect:** changing the hospital's tariff catalogue does not reliably change
automatic lab/imaging accrual. Registration/manual catalogue behavior must not
be mistaken for fixing departmental pricing. Unknown codes are flagged unpriced;
this is not a claim they are all silently charged zero.

**Bahmni reference:** B12, configurable stock/accounting workflow.

**Backend fix:** define stable lab/radiology charge-code mapping; reuse a single
facility/scheme/effective-date tariff resolver; copy exact Decimal price and
tariff ID onto the invoice item. Decide the approved accrual date basis
(service date/visit business date) before changing it. Preserve already-issued
invoices, unique source references and missing-tariff refusal. Do not add more
prices to Python dictionaries.

**Frontend fix:** in `features/billing/`, show resolved service code, tariff
date/version and unpriced lines; link authorized users to tariff management.
Never resolve money from today's browser catalogue or let an editable client
price override the server.

**Accept:** synthetic tariff change affects only new eligible accrual; old issued
invoice unchanged; scheme-specific/general precedence; timezone boundary;
missing/overlapping tariffs; replay produces one line; pharmacy-only billing
restriction remains. Browser: configure tariff → clinical result → preview/build
→ issue → payment; reconcile the persisted amount.

### F02 — Tariff maintenance and dormant add-item contract [P1; confirmed gap/latent defect]

**Evidence:** POST `/billing/charge-master` and POST
`/billing/charge-master/{id}/deactivate` exist; no frontend maintenance writer
was found. `features/billing/api/chargeMaster.ts` expects `{items:[]}`, but the
backend returns a list inside `Envelope.data`; `lib/api.ts` returns that data
unchanged. It also describes unsupported assumptions about filters.
`AddInvoiceItemModal.tsx` has a rejection path without catch/finally.
However, current line editing is deliberately disabled/refused: this is **not**
evidence that normal invoice collection currently hits that dormant modal.

**Fix:** add an authorized, effective-dated catalogue screen using existing
maintenance APIs; correct the list adapter to its real response; send
`active_only=false` when history is requested. Resolve contract fields from
OpenAPI and add actual response-shape tests. Do not enable freehand invoice
editing merely to make an old modal work. Remove dead edit callbacks/components
after checking references, or retain an explicitly unreachable legacy boundary.

**Frontend:** proposed `/billing/tariffs` or a reviewed tab; readable code,
category, Decimal price, scheme, start/end dates, active/history filters,
supersede/retire confirmation and server conflict feedback. Reuse HealthDoc MUI
and theme controls. Add role guard/sidebar/matrix entries together.

**Accept:** billing/admin allowed as backend policy specifies, receptionist
denied; inactive history loads; array response works; 403/409/network failure
renders error not empty list/spinner; current invoices are not repriced.

### F03 — eMAR cannot record an administration from the UI [P0 before clinical use; confirmed gap]

**Evidence:** POST `/nursing/medication-administrations` and status/reason schemas
exist. `frontend/src/app/nurse/emar/page.tsx` and
`components/tables/EMARTable/` display records; no frontend POST caller was found.
A nurse can inspect seeded/history rows but lacks the corresponding write path.

**Reference:** B10. Do not infer dose schedules from a text frequency field.

**Backend:** review duplicate-dose prevention before exposing the action. The
current service inserts a fresh row and the route has no explicit idempotency
argument. Add a tested idempotency boundary; define scheduled-dose identity,
amendment policy and concurrent administration rules with nursing/clinical owners.
Retain patient/admission/prescription ownership and authenticated actor checks.
Decide how “held/refused” event time differs from “administered” time.

**Frontend:** add admission-bound prescribed medication selection and “Record
given / held / refused” workflow. Display medication, prescribed dose/route,
scheduled/actual time, status and mandatory reason for missed doses. Never offer
arbitrary patient/prescription UUID entry. Refresh history after successful write;
disable duplicate submission and keep the same retry key after network ambiguity.

**Accept:** given, held, refused, missing reason, wrong patient/item, ended
admission policy, double click, retry, two nurses concurrently; correct record
survives reload and audit attribution. A screen-only eMAR test is insufficient.

### F04 — External referral results have no frontend intake/read-back [P1; confirmed gap]

**10 September implementation update — partial, not closed:**
`feat/external-referral-results` now implements encounter-scoped summary intake,
outside-result history, patient/order isolation, validation and exact-key
retries. It also exposes order fulfilment mode and fixes cross-facility result
replay. See [the implementation and acceptance report](external-referral-results-2026-09-10.md).
The follow-up adds a paginated cross-encounter inbox on Results review (including
completed visits), attachment upload/authorized temporary download controls,
and separate public HTTPS MinIO signing configuration. These have offline
regression coverage, not a new live acceptance run. Public storage hostname/TLS,
unknown-upload reconciliation, durable referred-test descriptions and a real
persisted browser journey remain outstanding. The original findings and broader
acceptance criteria below are retained as the historical and unfinished scope.
The latest browser repeat also caught an unresolved React render-depth error;
the first slice is not yet browser-accepted or ready to publish.

**Evidence:** `backend/app/orders/router.py` provides POST/GET
`/orders/{order_id}/external-results`. The service validates referral state and
file/patient/facility, records provider/summary/date/file and completes the order.
No `external-results` caller was found in frontend source.

**Reference:** B11. The backend is built; do not recreate it.

**Frontend:** extend `features/doctor/components/OrdersWorkspace.tsx` and
order/result detail APIs with a “Referred externally” queue, intake form and
version/history list. Fields: provider, observed date, summary and optional
authorized patient file. Show submitted state and who recorded it. Add the
nurse path only if it is intended in the workflow. Current backend roles are
doctor/nurse/admin—not lab_tech; widening that needs explicit policy review.

**Backend follow-up:** verify file upload/download permissions and result
review/sign-off semantics before calling an outside upload a locally verified
lab result. Decide whether append-only external versions need a separate
review event. Do not manufacture a lab FHIR context from arbitrary attachments.

**Accept:** referral → authorized upload/intake → order completed → doctor reads
the same result after reload; reject internal/cancelled order and wrong/erased/
foreign patient file; replay is idempotent; old result remains traceable.

### F05 — Patient-switch and failed-summary frontend state [P0; confirmed source defects]

**Evidence A:** `features/receptionist/AbhaIdentityPanel.tsx` initializes
identifier/session/linked state from props but has no patient-change reset.
`app/receptionist/registration/page.tsx` mounts it without a patient key.
Selecting another search result while it remains mounted can retain the earlier
patient's identity/OTP/success UI. Backend ownership checks help prevent a wrong
write; they do not make stale patient presentation safe.

**Evidence B:** `features/doctor/components/PatientSummarySidebar.tsx` starts
`Promise.all(...).then(...)` without catch and does not clear old patient/
allergy/history data before loading the next non-null patient. A rejected
request has no local error state; old clinical content can remain.

**Fix:** key identity/clinical child workspaces by patient ID; use per-request
generation or cleanup-local guards; immediately clear sensitive data on a
patient change; suppress late responses from prior patients; show independent
loading/error/unknown states. Reset OTP and transaction state on flow switch,
logout and expiry. A failed allergy read is **unknown**, not “no allergies.”

**Accept:** select A → delay A's response → select B → A completes; B must never
show A's demographics/ABHA/results or submit A's transaction. Reject each
summary request in turn; no unhandled rejection and no stale clinical card.
Repeat under React StrictMode and after session expiry.

## 4. ABDM completion packages

### A01 — Correct M1 credential purpose, expiry and continuation state [P0; confirmed gap]

**Evidence:** `identity/service.py::AbhaIssued` calls the enrolment/account
credential `linking_token`; `identity/router.py` persists it in
`patients.abha_linking_token_encrypted`. The returned transaction/expiry data
needed for later steps are not modeled fully. Separate expiring HIP link tokens
are already implemented in `hip/linking.py`; keep them separate.

**Reference:** B01/B02 for the multi-step workflow, not storage/security design.

**Backend:** introduce purpose-bound, short-lived server-side continuation
storage with facility/patient/staff ownership, gateway txn ID, stage, expires_at
and encrypted credentials. Preserve gateway-declared lifetimes; missing expiry
must not mean permanent validity. Distinguish gateway access, ABHA account/
enrolment and HIP X-LINK-TOKEN credentials in names, types, encryption context
and tests. Remove/reconcile old ambiguous credentials through a reviewed
migration/cleanup plan; do not reuse or expose them in the browser.

**Frontend:** consume an opaque continuation ID and allowed next actions, not a
token. Explain “identity verified; address/mobile setup pending” accurately.
Show expiry/restart and clear secret inputs on finish/switch/unmount.

**Accept:** wrong purpose, wrong staff/facility/patient, expired continuation,
duplicate ABHA, active-patient checks, logout and replays; assert no credentials
in browser storage, URLs, logs, JSON responses or outbox.

### A02 — Mobile verification continuation [P0 for required M1 branch; confirmed gap]

**Evidence:** HealthDoc has Aadhaar enrolment/existing-number OTP calls and an
optional mobile field, not the separate mobile OTP continuation. B01 has a
distinct `VerifyMobile.jsx` workflow.

**Backend:** after A01, implement stage-checked request/verify mobile operations
against the supplied current M1 collection. Preserve transaction correlation,
scope and the exact encryption rules. Do not infer mobile verification from
passing a mobile string in Aadhaar enrolment. Bound attempts/resend cooldowns;
handle successful remote verification followed by local persistence failure
without silently losing the proof or starting a second identity.

**Frontend:** replace “Mobile override” with required/optional states returned
by the server: masked destination, send OTP, verify, cooldown, wrong/expired OTP,
change number and safe restart. Client validation complements server checks.

**Accept:** same/different mobile branches required by the assigned checklist;
incorrect/expired OTP; failed send; lost response; retry; patient switch.
Mocked contracts first; actual SMS/OTP only with an authorized participant.

### A03 — ABHA address selection/creation and optional profile/card [P0/P1; confirmed gap]

**Reference:** B01 create/link address and ABHA card screens.

**Backend:** add continuation-bound suggestions and address creation with
canonical suffix, uniqueness/conflict handling and preferred address storage.
Refresh verified local identity only from a valid gateway result. For profile/
card, first confirm assigned scope; add a protected proxy with correct media
type/limits, no credential-bearing URL or automatic browser persistence.

**Frontend:** address suggestions, explicit chosen address, conflict correction,
progress and final identity summary. Add profile/card view/download only when
backend capability and checklist require it; use actual returned media, not a
fake locally designed “ABHA card.”

**Accept:** address conflict, malformed suggestion response, expiry between
steps, repeated create, no-address response, preferred-address mismatch, card
unavailable/wrong media type and authorization failure.

### A04 — Scan-and-Share reception tickets [P0 if demonstrated; confirmed source defect/gap]

**Evidence:** `external_router.py::profile_share` creates/matches a patient,
then derives the acknowledgement token with
`(patient.uhid or str(patient.id)).split("-")[-2]`. It does not create a
registration ticket corresponding to that token. A different UHID format can
also break this expression. A profile-share 202 is not an operational queue.

**Backend:** design a persistent facility/counter/business-date ticket with
stable callback correlation, expiry and status transitions. Allocate numbers
concurrently and atomically; repeat callback must return the same ticket.
Persist acknowledgement intent with the ticket. Review matching/deduplication
and provenance of profile identity; do not overwrite verified patient records
from an untrusted ingress request.

**Frontend:** add a Scan-and-Share queue at reception: counter/date, token,
received/accepted/expired state, masked identity, preview/confirm match, start
registration/visit and duplicate conflict. Display a QR only from validated
facility/counter configuration. Public display must remain PII-free.

**Accept:** PHR scan → same persisted token in acknowledgement and reception;
duplicate callback, simultaneous scans, wrong counter/service, expired ticket,
existing/new patient, unavailable acknowledgement transport and restart.

### A05 — Clinical finalization, author attribution and actual FHIR validation [P0; partial]

**Already implemented:** exact document references and dates, final/current
source checks, automatic publishers, scoped requests and historical registration.
There are **five HI types** and six source prefixes because both lab and imaging
map to DiagnosticReport. Do not advertise six types.

**Gap:** encounter closure is the current prescription finalization proxy.
Transfer pages freeze before first send, not at clinical sign-off. Lab results
lack separate verifier identity for this mapping; a nurse-authored discharge
may lack the practitioner registration required by the exporter. Structural
FHIR tests/sample builders do not prove NRCeS conformity or clinical correctness.

**Reference:** B04's dedicated builders. Bahmni's visit context must not replace
the user's decision: **one finalized document per HealthDoc care context**.

**Backend:** with clinical approval, version/sign source documents and capture
author/verifier/performer/provenance accurately. Add immutable source snapshot
or approved version semantics. Validate actual screen-generated documents
against assigned NRCeS packages, terminology and reference rules. Do not invent
PACS UIDs, diagnoses, registration numbers, measurements or signatures to pass.

**Frontend:** show draft/final/amended/superseded, signing clinician/time, reason
and readiness blockers. Lab verification and discharge sign-off must expose
actual role ownership. “Saved” is not “signed” and “linked” is not “shared.”

**Accept:** one selected prescription excludes siblings; amendment retains old
version; no pre-final export; original source author preserved; real generated
bundles validate for all declared types; validators are a required failing gate.

### A06 — Remaining callback durability and asynchronous timeout recovery [P0; partial]

**Evidence:** `callback_replies.py`, `jobs.py`, `job_runner.py` and migration
0067 already cover HIP consent/data-request and HIU consent acknowledgements.
Discovery/link/profile replies still have inline outbound work. An outbound
job marked done after acceptance does not prove a later callback arrived.

**Reference:** B05/B06. Do not copy early queue-acknowledgement or fire-and-forget
patterns simply because the reference uses a message broker.

**Backend:** persist reply intents with state changes for remaining callback
families; persist expected callback/deadline/outcome, not only transport status.
Handle absent/negative/malformed/out-of-order callbacks with approved stable-ID
retry rules, bounded attempts, dead-letter inspection and terminal-state guards.
Retain lease fencing, exact page replay and no consent/key renewal on retry.

**Frontend:** doctor sees “awaiting gateway callback,” last update and actionable
timeout rather than indefinite requested/sending. Admin sees failed stage,
attempts, deadline, safe reason and permitted retry. Do not enable bulk status
reset or dump callback bodies.

**Accept:** restart at commit/send/ack boundaries; remote accepted/local timeout;
callback never arrives; negative/error callback; reverse order and duplicate;
late callback cannot reopen revoked/expired/complete state.

### A07 — Clinically readable HIU viewer and safer navigation [P1; partial]

**Evidence:** `features/doctor/abdm/ExternalRecordViewer.tsx` already enforces
periodic access reads and renders untrusted data as text. Its generic recursive
object display is not equivalent to B07's medication/report/observation views.
`AbdmWorkspace.tsx` already searches patients and requests consent/data.

**Frontend:** add type-specific read-only adapters: medications with dose/route/
frequency, results with units and provided ranges, consultation sections,
discharge sections, and observation dates. Preserve document source, author,
record date, consent expiry, external provenance and “not imported” label.
Keep safe technical details expandable. Add explicit no-match/search-failed
states and reviewed search modes for patients lacking exact DOB; do not require
invented birth dates. Pass selected patient context from the doctor chart.

Never inject external XHTML, auto-fetch attachment URLs, invent ranges or
silently import external diagnoses/prescriptions. Downloads/print need a
separate consent/retention decision.

**Backend:** return supported presentation metadata without weakening read-time
facility/clinician/grant checks. Preserve generic safe fallback for unknown
resource fields; do not hide clinically important unknown content.

**Accept:** synthetic bundles of every supported type render clinically readable
facts; missing units/text explicit; malformed external HTML remains inert; switch
patient/record and revoke/expire clears access; unauthorized colleague denied.
Then test with a separately authorized external HIP.

### A08 — Ingress trust, service mapping and participant proof [P0; external dependency]

**Evidence:** official v3 routes use recipient/freshness/replay/correlation checks;
these headers do not cryptographically authenticate the sender. The legacy
private callback secret is not required on official routes. Outbound mapping
is single configured HIP/HIU/facility, not a general multi-facility service map.

**Fix:** confirm NHA-supported ingress trust and deploy it at the proper boundary.
Do not invent a signature scheme, require an unprovided secret from ABDM or
allow every source merely to remove 403s. Direct HIP→HIU pushes must remain
transaction/consent/crypto-bound. Validate bridge, service, HFR and clinician
registration independently of local seed fields.

**Frontend:** read-only readiness panel with safe configuration status and
blocked reasons, never credentials. Unsupported facility must show unavailable,
not route through another hospital's service ID.

**Accept:** wrong service/facility, malformed/stale/replayed header, unsolicited
artefact and wrong transaction fail; legitimate approved gateway/external HIP
can complete the assigned exchange. Live ingress health must be freshly checked;
old 502/404/405 observations are not current status.

### A09 — Close all clinical outbox/plaintext paths, not only new HIU writes [P0; confirmed source gap]

**Important correction:** new HIU received-content storage is protected, but
`integrations/abdm/fhir/service.py::_record_bundle` and
`record_discharge_bundle` still enqueue clinical Bundle payloads via the general
`outbox/service.py`. These are called from OPD visit closure and admission
discharge. The general outbox stores JSONB; a sensitivity label is not
application-level encryption. This is **an ongoing legacy producer path**, not
only historical residue. It does not prove data left this environment.

**Backend:** inventory each producer and intended consumer before removal.
Separate generic clinical projection needs from ABDM delivery. Replace clinical
payloads with approved identifier-only events or protected, bounded storage,
without breaking Mongo/document projection. Retire misleading legacy
`stub_not_sent` transmission records or name generated-versus-delivered status
accurately. Inventory and remediate historical rows/backups under approved
retention policy; do not delete auditable data ad hoc.

**Frontend:** admin must distinguish locally generated document, queued
notification, linked context, transfer sent, receipt acknowledged and rejected.
Do not show the old FHIR transaction timestamp as proof of delivery.

**Accept:** close OPD/discharge through actual APIs, inspect every new
integration/outbox event for plaintext clinical fields; verify required
projection still completes; retention, restore and duplicate-consumer tests;
new events cannot be sent to the wrong shipper.

### A10 — Revocation, cleanup, external identity interoperability [P0/P1; verification/policy gaps]

**Already implemented:** protected received store, row-bound crypto, exact
patient/context/date/type checks, key cleanup, monotonic callbacks, partial
transfer revocation and clinician-only access.

**Remaining:** continuous worker/reaper operation and database-contention tests;
restore of revoked/expired content; external HIPs that use only local patient
identifiers. Current strict ABHA binding is deliberate, not a bug to bypass.

**Fix:** define a reviewed transaction/patient/care-context binding strategy for
such HIPs, only if required, with wrong-patient adversarial fixtures. Add
receiver-versus-reaper races and key-loss recovery exercises. Preserve audit/
receipt metadata while erasing content according to approved retention.

**Frontend:** safe unavailable/revoked/expired states, source identity, blocked
reason without patient leakage; no “try another patient ID” workaround.

**Accept:** revoked before/after/mid-transfer; cleaner overlaps receive/read;
restore cannot resurrect allowed access; local-only identifier accepted only
under approved binding and wrong patient rejected.

### A11 — Historical registration and worker execution [P1; implemented, execution pending]

**Do not rebuild:** PR #539 provides the reviewed manifest-based tool and
`docs/abdm-historical-backfill.md`. It previews, locks, preserves authors,
rejects whole unsafe batches and atomically creates contexts/audits/jobs.

**Remaining:** approved manifest, data backup, source-author review, preview,
application execution and subsequent approved linking/notification. Existing
undated contexts use the separate reconciliation operation.

**Frontend:** historical repair is not a routine nurse button. If a management
UI is later required, design scoped preview/approval/correlation around the
service and authorized operator roles; do not expose privileged CLI execution.
For now show context readiness, not an uncontrolled “share all history.”

**Accept:** follow the runbook with approved synthetic first; compare identifiers
and audit state; review queue before worker start. A created context is not
consent and must not widen a confirmed link.

### A12 — Milestone evidence and required additional HI types [P0 for certification; external]

**Current types:** OPConsultation, Prescription, DiagnosticReport,
DischargeSummary, WellnessRecord. **Not implemented for sharing:**
ImmunizationRecord, HealthDocumentRecord, Invoice. Only build additional types
if the assigned checklist/product scope requires them; B04/B16 show clinical
source and mapper separation, not permission to fake records.

**Required inputs:** assigned case IDs and profiles, test participant/PHR,
approved OTP relay, HIP/HIU counterpart, service/registry identity, ingress
approval, clinical author rules, assessment/security requirements and owner.
No credentials or participant identifiers belong in this file or Git.

**Patient-initiated linking OTP is its own prerequisite (earlier G12).**
`hip/link_otp.py` already issues a random code, keeps a Redis HMAC digest with
TTL/attempt limits, and calls the configured relay. It refuses delivery when
`ABDM_LINK_OTP_DELIVERY_URL` is absent; the optional relay credential is
`ABDM_LINK_OTP_DELIVERY_TOKEN`. Configure a separately approved relay matching
the existing recipient/message/purpose/expiry contract. Verify actual receipt,
send rejection/timeout, wrong/expired code, bounded attempts, one-use proof and
database failure after proof consumption. This is HealthDoc's mediated linking
OTP, not the gateway's M1 Aadhaar/mobile OTP. Do not build a duplicate OTP
service, print the code to logs or bypass it with a fixed demo code. The PHR
must confirm only the intended selected contexts; failure should leave a clear
restart/recovery state in the staff link-status UI.

**Supplied Postman collections are references, not an execution script.**
Use `scripts/check_abdm_collections.py` for the existing read-only path audit.
Earlier inventory found a direct production-host request and a legacy session
request; do not run a collection runner against all files or print environment
values. Compare the specific request body, response, error and callback shape
for each selected case. Face authentication, Scan-and-Pay and every PHR/account
endpoint are not automatically HealthDoc requirements merely because a file
contains them.

**Controlled milestone rehearsal order, once prerequisites are satisfied:**

1. **Freeze the environment:** record deployed source, schema, required workers,
   approved sandbox-only destinations and identities. Prove ingress reaches
   that revision and that the authorized participant/counterpart is available.
2. **M1 from reception:** find/register the synthetic test patient; complete
   required creation and existing-ABHA verification branches, mobile/address
   continuations and local verified binding. Include duplicate, wrong/expired
   OTP and patient-switch failures. If assigned, show the same persisted
   Scan-and-Share ticket in the PHR acknowledgement and reception queue.
3. **M2 from clinical screens:** finalize the declared document types; inspect
   precise context creation; exercise required HIP-initiated and PHR-initiated
   discovery/linking, including real mediated OTP delivery. Confirm link before
   new-context notification; have an approved external HIU request a narrower
   permitted scope. Prove acknowledgements, encrypted transfer, external receipt,
   actual document validation and restart/revoke/expiry negatives.
4. **M3 from the doctor workspace:** request a separate HIP's records; grant a
   narrower permission in the PHR; fetch the artefact and request only that
   scope. Receive/decrypt/validate/store, then display readable source-labelled
   records in the normal browser. Prove wrong-patient, unauthorized colleague,
   partial transfer, duplicate, revocation and expiry behavior, including cleanup.
5. **Close the evidence:** correlate each assigned case with redacted results,
   unresolved exceptions and reviewer outcome. Two HealthDoc instances passing
   each other are useful internal tests, not independent protocol proof.

**Done means:** each case has deployed commit, role/action, redacted request
correlation, actual external result, validated clinical document, negative tests
and review outcome. NHA certification is an external decision; no engineering
deadline can guarantee it tomorrow.

## 5. Core hospital functionality beyond ABDM

### H01 — Structured laboratory results and approved critical rules [P0/P1; confirmed gap]

**Evidence:** `features/lab/components/LabWorklistPanel.tsx` requires JSON entry/
amendment. `pathology/router.py::CRITICAL_THRESHOLDS` contains one hardcoded
haemoglobin rule. Worklist filters/paging, results, independent verification,
amendment and MIS already exist. Do not replace them.

**Reference:** B11, laboratory-specific data capture.

**Backend:** agree/version analyte and panel definitions, value types, units,
allowed precision, coded answers, reference ranges, critical rules and
age/sex/context applicability with lab governance. Validate both result entry
and amendment against the selected version; retain original raw/external data
where required. Do not invent clinical thresholds from sample data.

**Frontend:** schema-driven fields and units, requiredness/inline errors,
normal/abnormal/critical indication derived from approved server rules,
preliminary/final status, independent verify review, change diff and amendment
reason. JSON may remain a restricted diagnostic view, not the normal technician
entry method.

**Accept:** numeric/coded/text panels, decimal and blank optional fields, invalid
unit/value, old schema versions, unauthorized rule edit, author self-verification
refused, second technician releases and doctor reads corrected version.

### H02 — Critical-alert delivery beyond one API process [P0 before relying on alerts; confirmed gap]

**Evidence:** lab/doctor subscriptions exist, but
`_critical_alert_subscribers` is an in-memory dictionary of asyncio queues.
An alert published in another worker process cannot reach those subscribers.
`NotificationHistory` persists an event, but an SSE toast is not an
acknowledged/escalated clinical alert workflow.

**Backend:** use facility/recipient-scoped shared delivery, ideally durable event
IDs with replay/catch-up; publish after commit. Define acknowledgement,
responsibility/escalation and downtime fallback with clinical owners. Bound
queues and heartbeat/reconnect behavior; do not leak patient details publicly.

**Frontend:** persistent critical-alert list with unread/acknowledged state,
connection-loss indication, safe link to result, and escalation status. Toasts
supplement the list. Implement actions only after matching API/policy exists.

**Accept:** entry on process A, subscriber on B; disconnected browser returns;
duplicate event; rollback must not announce an uncommitted result; only intended
doctor/facility lab staff receive it. A clinical delivery SLA needs owner approval.

### H03 — KPI/report producer and publication lifecycle [P1; confirmed gap]

**Evidence:** `backend/app/reports/router.py` only reads `KpiSnapshot`.
Search found no producer in `backend/app` or `scripts`. The UI correctly says
no snapshots rather than zero. Live billing/lab MIS is separate and present.

**Reference:** B13, explicit report definitions/queries/templates.

**Backend:** approve KPI catalogue, numerator/denominator, period/timezone,
source inclusion and corrections. Build scheduled idempotent computations for
closed periods; record definition/version/run status and reconciliation inputs.
Do not recompute published historical figures silently on read. Bound the
reader with validated periods/date ordering and pagination where needed.

**Frontend:** `features/reports/` should distinguish not computed, processing,
failed, computed zero and published. Show numerator/denominator, source date,
definition and export status. Authorized regenerate/revision controls require
an API and approval policy.

**Accept:** seed real synthetic events → run producer → correct totals after
reload; duplicate run; late correction; month/timezone edges; empty vs zero;
cross-facility isolation; exported numbers match displayed published version.

### H04 — Clinical documents in the patient portal [P1/P2; confirmed scope gap]

**Evidence:** `app/patient-portal/page.tsx` and `patients/portal_self_router.py`
provide ABHA/consent/access-history views, not visits/results/prescriptions/
discharge document viewing. Verified user→patient binding is already built.

**Reference:** B15 for staff document UI; dedicated Bahmni portal repositories
were not cloned here, so their implementation is not verified by this review.

**Backend:** add self-scoped finalized document list/read APIs using the existing
binding dependency. Define patient-release timing, sensitive results, proxy/
guardian/dependent access and download policy before adding them. Never take a
browser-supplied patient ID as authorization.

**Frontend:** tabs for My visits, Prescriptions, Results, Discharge and permitted
documents; date/type filters, source/status, safe viewer/print and access errors.
Keep privacy/consent history and clear verification-required state.

**Accept:** unbound/other account refused; only this patient’s releasable versions;
unreleased/amended/erased documents handled; large-file errors, download audit,
mobile and keyboard journeys. Clinical release policy is an external dependency.

### H05 — PACS device/archive/viewer integration [P1/P2; partial/verification gap]

**Implemented:** imaging orders, schedule/cancel/reschedule, report versions,
PACS study UID and FHIR report inspection. A UID alone is not image retrieval.
No complete device→archive→patient viewer flow was established in this review.

**Reference:** B14.

**Backend/operations:** select/configure PACS and supported DICOM/DICOMweb
interfaces; bind study/accession to patient/order with reconciliation; secure
viewer sessions and image access, retry, audit and archive recovery. Keep
images outside the ordinary JSON API. Validate modality worklist/device scope
before claiming it is supported.

**Frontend:** permission-gated “View study,” report/image linkage, archive
unavailable/mismatch states and restricted viewer session. Never substitute an
arbitrary URL/UID or show another patient's study on mismatch.

**Accept:** synthetic modality image → archive → exact report/order → authorized
viewer; wrong patient/accession denied; expired session; unavailable archive;
restored images and metadata remain consistent.

### H06 — Configurable forms, specialty documentation and longitudinal chart [P2; scope gap]

**Evidence:** HealthDoc has fixed SOAP, diagnoses, orders, vitals and several
typed forms. A comparable implementer-facing versioned form definition and
runtime control registry was not found. B08 includes configurable controls and
observation-form hooks. Existing patient history is not a blank shell.

**Backend:** agree initial form/specialty list; version definitions, coded
concepts, validation, drafts/finalization, provenance and migration rules.
Prefer a bounded renderer over arbitrary executable user-supplied scripts.
Unify longitudinal record references without widening encounter/facility access.

**Frontend:** reusable form renderer, sections, repeating groups, coded search,
draft/resume and finalization; chart timeline with filters/trends and source
labels. Configuration preview must use synthetic data. Retain approved clinical
workflow rather than reproducing Bahmni's Angular or Carbon component hierarchy.

**Accept:** a saved old form renders after a definition change; draft not exported;
offline/network failure does not falsely report saved; keyboard paths; cross-role
gating; version/amendment history and clinical review.

### H07 — Appointments and teleconsultation [P2; scope gap]

**Evidence:** roster/day queues and all visit-type labels exist. No complete
appointment booking/service calendar or teleconsult video workflow was found.
A `teleconsult` visit enum is not a working remote consultation service.
Reference B09; any separate backend module needs version/dependency review.

**Backend:** define services/durations/providers, availability/unavailability,
timezone, overlap/no-show/cancellation and booking identity; connect arrival to
existing visit/token flow, not duplicate it. Teleconsult additionally needs
consent, secure session/provider choice, connectivity fallback and policy.

**Frontend:** receptionist calendar/day list, book/reschedule/cancel/check-in;
patient confirmation and doctor schedule. Teleconsult room only after service/
security decisions; show unavailable honestly if not selected for release.

**Accept:** concurrent last-slot booking, blackout, timezone boundaries, cancel/
rebook, late arrival, no-show, check-in once, doctor access and session expiry.

### H08 — Inventory/procurement completeness [P1 verification; P2 depth]

**Implemented:** purchase orders, transfers, GRN, indents, adjustments, expiry/
alerts, HOD approvals. Do not repeat “backend-only procurement.”
Reference B12; HealthDoc targets `features/inventory/`, `inventory/` and
`pharmacy/` backend modules.

**Next:** action-level test PO approval → partial receipt → independent verify
→ batch stock; transfer dispatch/partial receive → discrepancy → final balance;
indent raise/HOD approve/issue; adjustment maker-checker; dispense partial
quantity/controlled approval/return and financial reconciliation.

**Build only confirmed gaps:** supplier returns, physical stock-count approval,
lot recall, units-of-measure conversion, reorder automation and warehouse
accounting parity require discovery/product decisions. Do not claim they are
all absent or required from a route count.

**Frontend:** expose remaining/received quantities and batch/expiry clearly,
approval owner, rejected reason, state-specific actions, safe conflict refresh.
No float arithmetic for quantities; server supplies authoritative availability.

**Accept:** action matrix above, expired/insufficient batch, duplicate receipt,
concurrent stock consumption, transfer mismatch, reversal and refusal of
self-approval. Screen mounting two default tabs does not cover the other tabs.

### H09 — Billing completeness, schemes and accounting [P1/P2; confirmed scope gaps]

**Evidence:** payments/refunds/MIS and separated billing authority are built.
`aggregate_unbilled_charges` covers lab/radiology/pharmacy, explicitly excludes
IPD stay/procedure/blood aggregation. `check_pmjay_eligibility` is a stub;
ABHA verification is not evidence of benefit eligibility. No Odoo-equivalent
general ledger/period-close product was established.

**Backend:** after F01, approve source-event/accrual rules for bed-days,
procedures/packages, discounts and scheme adjustments; implement deduplicated
ledger events and reversal semantics. Eligibility/claims need their own verified
integration and finance approval. Choose audited accounting export/integration
versus building a general ledger as a separate architecture decision.

**Frontend:** identify omitted/unpriced services, proposed vs posted charges,
covered vs unknown eligibility, outstanding/partial payments and authorized
reversal. Keep manual discount/scheme/line editing unavailable until governed
APIs exist; never infer “eligible” from a successful ABHA flow.

**Accept:** complete inpatient bill reconciles to approved source events;
duplicate accrual/reversal; rate revisions; rounding; refund authority; scheme
unavailable; closed-period handling. Get finance sign-off on actual examples.

### H10 — Terminology and clinical decision support [P2; partial/clinical dependency]

**Evidence:** code-aware allergies/prescriptions exist.
`backend/app/allergies/interactions.py` is explicitly a small hardcoded,
non-blocking pair-warning stub. This is not a comprehensive medication safety
engine or an approved clinical reference.

**Reference:** Bahmni's terminology-related ecosystem is described in the
earlier repository plan; its separate terminology servers/data were not locally
validated here. B08/B16 show coded clinical integration.

**Backend:** choose approved terminology/rules source and licensing, versions,
coverage, update process and downtime behavior. Separate allergy matching,
interaction advice and clinical blocking policy. Record uncheckable drugs as
unknown, not interaction-free. Do not grow handwritten clinical advice lists.

**Frontend:** coded autocomplete with readable term/unit/strength, warning source
and version, coverage/unavailable notice and documented override where policy
allows. No “safe prescription” badge based on the current stub.

**Accept:** synonym/ingredient mapping, missing code, rule-source outage,
version change, clinically reviewed examples, override audit and accessibility.

### H11 — OT, immunization, general health documents and blood bank [P3 unless scope requires]

**Confirmed:** `backend/app/ot/router.py` is ping-only despite OT models;
`blood_bank/router.py` is ping-only. No end-to-end immunization workflow was
found. These are not complete modules merely because tables exist.

**Reference:** B16 for immunization and B04 for HealthDocumentRecord. A complete
Bahmni OT backend was not among these 23 clones; no Bahmni blood-bank parity
claim is made.

**Implementation, if selected:** OT scheduling/theatre/team/conflict/surgical
record and sign-off; immunization product/lot/dose/date/performer/reaction with
clinical schedule approval; protected document upload, review and release.
Blood-bank donor/component/testing/crossmatch/issue/traceability needs a
specialist-approved specification, not a generic stock form.

**Frontend:** purpose-built workflows only after domain APIs/rules; absent
modules remain hidden/explicitly unavailable, not clickable empty shells.

**Accept:** approved domain case lists, traceability, author/version rules and
scope tests; extra ABDM types added to validators/builders only after real
source workflows exist.

### H12 — Print/PDF, labels, accessibility and everyday usability [P1/P2; verification gap]

**Implemented:** receipt/prescription print views and `e2e/print-pdf.smoke.mjs`.
This does not establish every lab/discharge/label/patient-card print format.
References B15 and the main configuration/clinical sources.

**Next:** catalogue each required output and test real printer/page dimensions,
font/Indian-script rendering, multiple pages, long names, quantities/units,
headers/signatures, cancelled/amended watermark and barcode/QR scan accuracy.
Server-rendered content must use the same authorized finalized source.

**Frontend:** print-preview layout distinct from the application shell, avoid
sidebar clipping, readable error states, focus return, labelled inputs, keyboard
operation, 200% zoom, narrow viewport and adequate contrast. Preserve HealthDoc
logo/colors and existing components. Do not make cosmetic changes that hide
failure states or remove consent restrictions.

**Accept:** source values match PDF/print, no clipped critical fields, permission/
expiry denied, safe CSV cells, keyboard-only full journey and manual visual review.

## 6. Shared frontend implementation rules

These apply to every package, not as a separate redesign.

1. **Keep the existing UI.** Reuse `@/styles/theme`, `surface-card`, existing
   buttons/modals/tables/status chips, typography and responsive spacing.
   Bahmni/Carbon is a behavior reference; do not import its theme or introduce a
   second design system. Extract shared HealthDoc controls where useful.
2. **Patient context is a security boundary.** Key patient workspaces, clear
   old state immediately, ignore stale responses and test rapid switching.
   A previous patient's result must never remain under a new patient's name.
3. **Model async states explicitly.** Loading, empty, unavailable, forbidden,
   expired, stale conflict, validation error and transport error are different.
   Every started promise has an error/finalization path. Never convert a failed
   clinical read into `[]`, zero, “normal” or “none.”
4. **Validate contracts, not only URLs.** Check the actual envelope data shape:
   bare arrays versus paginated objects, nullable values, decimals-as-strings,
   dates versus datetimes, enum vocabulary and 204/no-content responses.
   TypeScript generics alone do not validate a server response.
5. **Forms must be submittable and explain failures.** Every required schema
   field is rendered or intentionally initialized. Empty optional numbers do not
   become NaN; Decimal inputs allow decimals; blank UUID/date values are omitted
   where appropriate. Field-level messages plus focused summary; toast is a
   supplement. Use the project's safe error mapper, never SQL/raw gateway text.
6. **Retries preserve operation identity.** Generate one idempotency key per
   logical action; retain it across ambiguous retries; change it only for a new
   body/action. Double-click disabling is not server-side deduplication.
7. **Role and module gating stay aligned.** Update backend permissions,
   `config/roles.ts`, `lib/auth/routes.ts`, sidebar and role dashboard tests
   together. Hidden navigation is not authorization. Facility module unavailable
   must not be rendered as “no patients.”
8. **Handle refresh safely.** Clean up streams/timers; prevent StrictMode cleanup
   and stale request races. Do not solve aborted-request failures by globally
   ignoring errors in smoke tests. Background refresh should preserve valid
   input while never preserving revoked sensitive content.
9. **No mock authority.** Do not use fixture patients, prices, thresholds, status
   counts or synthetic success in production paths. Static labels and styling
   are not the same as hardcoded clinical/business data. Remove proven-dead mocks
   only after checking imports/routes/tests.
10. **Accessible by default.** Labels, aria-invalid/describedby, live status,
    keyboard focus, modal focus return, visible busy state, responsive tables,
    correct input autocomplete and clear date/timezone labeling.
11. **No secret/PHI persistence for convenience.** No tokens/OTP/Aadhaar in
    localStorage, URLs, logs, analytics or screenshots. External text/HTML/
    attachment URLs remain untrusted. Review clinical draft storage separately.
12. **Read local framework guidance.** Before future frontend code edits, read
    `frontend/AGENTS.md` and the relevant installed Next.js guide; do not apply
    a remembered older Next API blindly.

### Proposed frontend workboard

| Owner | Existing surface | Work | Dependencies |
|---|---|---|---|
| Reception FE | Registration / ABHA panel | Patient-safe state, M1 stepper, mobile/address, optional card | F05, A01–A03 |
| Reception FE + backend | Reception queue | Scan-and-Share tickets, counter and status | A04 |
| Doctor FE | Patient summary + ABDM workspace | Failed-summary states, context-safe navigation, clinical record views | F05, A07/A10 |
| Nurse FE | eMAR / ward | Administration actions, missed-dose reasons, post-save refresh | F03, clinical dose identity |
| Lab FE | Worklist / MIS | Structured entry, independent verify diff, persistent alerts | H01/H02 |
| Doctor/results FE | Orders / results | Referred-result intake and history | F04 |
| Billing FE | Billing / proposed tariff tab | Tariff admin, accurate preview/unpriced explanations | F01/F02/H09 |
| Reports FE | Reports | Compute/publication states, periods, reproducible export | H03 |
| Patient FE | Patient portal | Released clinical documents; preserve binding/privacy | H04 + release policy |
| Imaging FE | Radiology | Study viewer/link/status, image mismatch handling | H05 + PACS |
| Platform/quality FE | Shared components | Response-shape guards, async error/empty states, roles/a11y/print | All applicable packages |

Do not expose a proposed control before its API, authorization and tests exist.

## 7. Operational and release work

### O01 — Recovery, monitoring and production evidence [P0/P1; verification/external]

HealthDoc already has `infra/observability/` Prometheus/Grafana configuration,
PostgreSQL backup/restore scripts, ZAP tooling and load-test tooling. This review
did not verify their live deployment or current reports. Do not label them
missing merely because external acceptance is pending.

Required completion:

- App/worker health, queue age, dead jobs, awaiting callbacks, key/consent expiry,
  rejected records, dependency failures and replay spikes need actionable alerts
  with named receivers/runbooks. A Grafana JSON file is not an alert received.
- Rehearse restore of PostgreSQL plus MongoDB notes, MinIO files, Keycloak realm/
  users, Redis-dependent sessions/jobs, encryption keys and actual image archive
  if added. Define approved RPO/RTO/PITR scope. Verify decryption, not row counts only.
- After restored state, revoked/expired consent must still refuse content; do not
  restart all shippers and accidentally resend historical requests.
- Run authenticated clinical load and multi-process SSE/worker tests separately
  from resource-heavy browser sweeps. Compare actual latency/error objectives.
- Run current dependency/image audit and approved authenticated ZAP/VAPT scope;
  attach dated reports and resolve the assigned severity criteria. Old “clean”
  docs are not present-day audit evidence or a legal compliance determination.
- Execute API/worker with approved origins/registry/service IDs and a checked
  deployed revision. Changes to tunnel, bridge or secrets need separate approval.

### O02 — Consent/DPDP governance and historical-data cleanup [P0/P1; policy/execution]

DPDP governance screens and backend exist. Real officer appointments, grievance
SLA, responsibility, retention and file-erasure/audit handling require the
organization's approved policy. This report does not interpret statutory duties
or select clinical/audit retention periods.

Reconcile patient-file erasure, external received records, legacy clinical outbox,
backups, audit/access metadata and print/download copies. Show not-configured
honestly; never seed a fictitious officer/approval for a demo. Test approved
erasure/access denial and metadata preservation with synthetic data.

### O03 — Release/evidence truthfulness [P1; confirmed documentation drift]

The role report dated 6 September still shows receptionist billing access,
while the newer billing separation deliberately removes it. Older WASA/ABDM
documents say “code-ready” before later confirmed gaps. These are historical
records, not the current acceptance matrix.

Keep this report's baseline explicit. Generate fresh role/action evidence from
the sidebar plus agreed capability/action catalogue, not screenshot counts.
Update the current status page while preserving dated evidence. Distinguish
feature merged → deployed → configured → internally tested → externally
accepted → certified.

All code changes should follow feature branch → reviewed staging PR → separate
staging-to-main promotion. No feature-to-main PR, force merge, secret commit,
blanket test skip or hidden expected-error exception.

## 8. Test matrix and “done” definition

### Role/action acceptance matrix

| Role | Mandatory actions to prove; not just page loads |
|---|---|
| Receptionist | Duplicate search; permitted new registration; patient switching; M1 OTP/mobile/address; Scan-and-Share ticket; OPD and non-OPD visit without seed-only roster assumption; billing access denied. |
| Doctor | Queue → patient summary → consultation → orders/prescription → closure; allergy lookup failure; external referral result; ABDM link/consent/data/clinical read; wrong-patient and stale response negatives. |
| Nurse | Admission/occupancy; partial vitals/decimal entry; eMAR given/held/refused with idempotency; task/handover; discharge and approved clinical author/sign-off. |
| Lab tech + second verifier | Filters/pagination; sample/result; structured validation; self-verify refusal; independent release; amend/current version; MIS; cross-process critical alert and acknowledgement. |
| Radiology tech / signer | Schedule → reschedule/cancel; machine conflicts; scan complete; report/sign-off; version refresh; synthetic study/viewer; wrong accession denied. |
| Pharmacist | PO/GRN/stock actions permitted by role; batch/partial dispense; controlled approval; return/expiry; pharmacy-only invoice boundary; concurrent stock failures. |
| Billing | Current tariff and revisions; departmental build; missing tariff; issue/partial/full payment; receipt; authorized refund rules; no silent zero or float drift. |
| HOD | Roster creation without relying on seeded entries; department scope; requested-indent approval; wrong department and self-approval policy. |
| Supervisor + second supervisor | THID/UHID maker-checker; self-approval denied; approved merge/unmerge; KPI access, no billing privilege escalation. |
| Admin | Facility staff/module governance, tariff authority per policy, DPDP configuration, dead-job diagnosis/retry, approved maintenance preview; other facility denied. |
| Auditor | Audit/access filters and matching exports, published report reconciliation, integrity/status visibility; writes denied. |
| Patient | Unbound refusal; verified self access; own released documents only; no guessed patient-ID access; correct consent/access history. |
| Emergency | THID registration and approved workflow; non-OPD route without queue; session expiration and safe return path; clinical escalation policy. |
| Superadmin | Platform facility/account boundary only; no automatic facility clinical/billing access. |
| Public | Queue display only intended non-PII fields; no patient identity, private record, staff tokens or callback secret exposure. |

### Required layers for each work package

1. **Contract tests:** actual request/response and errors, required fields,
   arrays/envelopes, decimals/dates/enums; not merely path presence.
2. **Service/API tests:** authorization, facility and patient scope, terminal
   state, idempotency, conflicts, audit and data persistence.
3. **PostgreSQL tests:** real locks, uniqueness, row versions, concurrent writes,
   audit triggers and transaction rollback where applicable; no SQLite-only
   concurrency proof.
4. **Frontend tests:** field errors, async rejection, empty vs unknown, late
   responses, double click, role guards and StrictMode lifecycle.
5. **Real Keycloak browser journey:** own normal UI → authenticated calls →
   persisted state → downstream role sees correct result → reload.
6. **Clinical/security/finance review:** required for rules, authorship, tariffs,
   retention and scope changes, not replaced by developer approval.
7. **External tests:** ABDM/PACS/OTP only after authorized counterpart and
   environment approval; record case-level evidence without secrets.

Existing local gates for implementers:

```bash
make test-pg
make contract
make audit-deps
cd frontend
npm test
npm run typecheck
npm run build
```

Use existing `frontend/e2e/` harnesses following
`docs/local-role-verification.md`, with separate synthetic data and a correctly
configured stack. Do not run a bulk browser sweep concurrently with the heavy
backend gate and misclassify resource contention as a code regression.

Definition of done: linked acceptance case, before-fix failure or source proof,
reviewed implementation, tested persisted/downstream outcome, forbidden-role/
patient negatives, updated docs and staged CI green. If external approval is
pending, mark implementation complete and external verification open.

## 9. Implementation order and realistic planning

### Suggested sequence

1. **Immediately:** F01 wrong-money source, F05 patient-state safety, A09 legacy
   clinical outbox; confirm A08/A12 external requirements. These must not be
   concealed behind UI polish.
2. **Core workflow closure:** F02 tariffs, F03 eMAR, F04 outside results,
   H01 structured lab and H02 alert reliability. Clinical definitions gate
   clinical rule/schedule work.
3. **Milestone completion:** A01 → A02/A03 → A04; A05/A06/A07 in parallel with
   approved ingress/clinical inputs; A10 cleanup/interoperability; A11 approved
   backfill/worker execution; A12 real cases.
4. **Operational proof:** O01/O02 plus role/action regression matrix and truthful
   release evidence O03. Production promotion follows review, not the calendar.
5. **Broader parity:** H03–H12 as selected by the product roadmap. Do not let
   theatre/ERP/form-builder expansion become a hidden prerequisite for the
   already-declared five-type ABDM pilot.

### Effort ranges for assigning work

These are **engineering person-days** (implementation, focused tests and review),
not elapsed deadlines. They overlap; do not sum blindly. Assumes engineers
familiar with HealthDoc, working test environments and prompt decisions.

| Package group | Planning range | Main uncertainty |
|---|---:|---|
| F01/F02 billing tariff correction and maintenance | 3–6 | Finance charge-code/date/overlap decisions; existing invoice rules |
| F05 patient/async state safety + regression sweep | 1–3 | Number of additional affected mounted child components |
| F03 eMAR action and duplicate-dose protection | 3–6 | Dose identity/scheduling and correction policy |
| F04 external referral intake/read-back | 2–4 | File access/release/review semantics |
| A01–A04 M1 lifecycle/mobile/address/scan queue | 6–12 | Current contract branches, participant/OTP and queue policy |
| A05–A07/A10 FHIR, recovery and usable HIU workflow | 6–12 | Clinical versions/identifiers, callback behavior, profile validation |
| A08/A09/O01/O02 security/retention/recovery closure | 5–10 plus approvals | Legacy consumers, keys/backups/ingress and approved retention |
| H01/H02 structured lab and durable alerts | 4–8 | Approved analyte catalogue/critical/escalation policy |
| H03 KPI producer and publication UI | 3–6 for an agreed initial KPI set | Definitions, reconciliation and revisions |
| H04/H05 patient documents / PACS | 4–8 / 5–12 | Patient-release policy / external image infrastructure |
| H06–H11 broader parity | Scope and estimate separately | Form engine, booking, accounting, CDS, OT and specialist modules are projects, not dashboard fixes |

With two experienced backend engineers, a frontend engineer and daily QA/DevOps,
a **focused milestone pilot** can be planned in roughly **1–2 working weeks**
after required inputs are available, with contingency for interoperability.
Core product hardening plus clinically approved workflows is a broader
multi-week program. Full Bahmni parity cannot responsibly be promised in one
day or by a single percentage. NHA/security assessment scheduling is additional
external lead time.

### Decisions the implementation team needs

| Decision/input | Required for |
|---|---|
| Current assigned NHA cases/profiles/HI types and authorized participants | A02–A12; certification evidence |
| Exact one-document finalization/version/signing rules; lab verifier/discharge author | A05/H01/F03 |
| Approved analyte ranges/critical thresholds and acknowledgement/escalation SLA | H01/H02 |
| Tariff code mapping, service-date basis, scheme, bed-day and reversal rules | F01/F02/H09 |
| Patient-release/guardian/download policy | H04/A07 |
| Per-facility/counter Scan-and-Share ticket lifecycle | A04 |
| NHA-compatible ingress, service registry and supported external identifier binding | A08/A10 |
| Legacy outbox consumers, retention, backup/key recovery and worker-start approval | A09/A11/O01/O02 |
| Which optional Bahmni capabilities belong in this release | H05–H11 |

## 10. Ticket/handoff template for another developer or coding agent

Copy a work-package ID from this file into a small ticket. The following is an
implementation specification template, not authorization to deploy or merge:

```text
Work package:
Current HealthDoc commit / branch:
Reference Bahmni repository, commit and exact source path:
Confirmed existing behavior to preserve:
Failing/missing user journey and evidence:
Backend API/data changes (proposed vs already existing):
Frontend route/components, role, state transitions and errors:
Patient/facility/role boundaries:
Idempotency, concurrency, audit and retry behavior:
Clinical/product/finance decisions required:
Migration/backfill/rollback impact:
Acceptance cases, including negative and downstream cases:
Test commands/results and evidence location:
Known limitations / external verification still open:
PR target: staging; separate promotion staging → main.
```

Instructions for implementation review:

- Verify current source before coding: these files will change after this report.
- Do not downgrade new v3 code to match Bahmni's older APIs.
- Do not substitute another clinician/identity, broaden a grant or share a visit
  when only one document was selected.
- Do not copy GPL/AGPL/MPL or other source without a component-specific license/
  attribution review. A behavioral reference is not a license clearance.
- Do not run real OTPs, backfills, bridge updates, worker starts, migrations on
  application data, destructive cleanup or production promotion without scope
  approval. Sandbox credentials still control external actions.
- Never hide a failure with mock data, unconditional success, global 4xx ignores,
  skipped collection or a role change that bypasses the intended boundary.

## 11. Reproducible reference inventory

All 23 working trees were clean at this review. HEADs identify inspected local
snapshots, not a claim of latest upstream release or runtime compatibility.

### BahmniIndiaDistro (8)

| Repository | HEAD | Commit date |
|---|---|---|
| ABHA-Verification | de1f6e6 | 2024-06-19 |
| bahmni-india-package | 9dfb03c | 2024-05-24 |
| health-information-user | 86a5751 | 2024-06-21 |
| hip-atomfeed-listener | 327ff02 | 2025-02-05 |
| hip-service | 764e19e | 2024-12-13 |
| hiu-db-initializer | 3a52b99 | 2025-03-12 |
| hiu-ui | 0276cb0 | 2024-10-09 |
| openmrs-module-hip | a1bb65e | 2025-01-21 |

### Bahmni main (15)

| Repository | HEAD | Commit date |
|---|---|---|
| OpenElis | c399016a | 2026-06-17 |
| bahmni-apps-frontend | e9a18363 | 2026-09-08 |
| bahmni-core | 04a5299ed | 2026-08-27 |
| bahmni-docker | c32e9a6 | 2026-08-28 |
| bahmni-module-fhir2-addl-extension | 046d889 | 2026-09-07 |
| bahmni-module-immunization | b59b382 | 2026-09-07 |
| bahmni-odoo-modules | c7bfa18 | 2026-07-16 |
| bahmni-reports | 5b7f95b | 2026-09-03 |
| openerp-atomfeed-service | 6c4f271 | 2025-12-16 |
| openmrs-distro-bahmni | 07bb267 | 2026-08-27 |
| openmrs-module-bahmniapps | 24ec65d9a | 2026-08-27 |
| openmrs-module-ipd | f3eeb65 | 2026-08-28 |
| openmrs-module-ipd-frontend | 4b25c43 | 2026-09-03 |
| pacs-integration | a53015c | 2026-07-16 |
| standard-config | 9a006d3 | 2026-09-02 |

### Supporting HealthDoc documents

- [Earlier ABDM comparison and original G1–G13 findings](bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md)
- [Distribution/repository evaluation plan](bahmni-comparison-and-repository-plan-2026-09-07.md)
- [Historical registration procedure](abdm-historical-backfill.md)
- [Local migration, worker and recovery runbook](abdm-local-verification-and-recovery.md)
- [Billing-specific verification](billing-abdm-readiness-2026-09-06.md)
- [Role evidence, dated historical results](role-verification-evidence.md)
- [How to regenerate local role verification](local-role-verification.md)

**Review method:** the architecture-review skill organized this handoff around
complete workflows, boundaries, dependencies and measurable acceptance criteria.
Only this report was created for this request; no application code, services,
database state, Bahmni checkout, branch promotion or external patient workflow
was changed.
