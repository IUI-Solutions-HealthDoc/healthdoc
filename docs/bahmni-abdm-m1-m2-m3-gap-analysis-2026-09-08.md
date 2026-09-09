# Bahmni vs HealthDoc: ABDM M1, M2 and M3 implementation and closure plan

Review date: 8 September 2026. HealthDoc baseline: `a9d7cc4600bbe1610c15e383e215f618c8d39218`, branch `fix/billing-dashboard-validation-and-invoice-list`.

## Implementation update — 9 September 2026

PR #537 (`fix/abdm-milestone-closure`) merged into staging after all four active
CI checks passed. Follow-up historical registration work is on
`fix/abdm-historical-registration`. The sections below describe the original
audit baseline; use this update for implementation status.
The user selected **one finalized document per care context**, not an entire visit.

| Finding | Implemented locally | Still required before closure |
|---|---|---|
| G1 | Migration 0061 stores exact accepted request scope. Workers recheck consent, linked context, source final/current state and key expiry between pages. Unknown legacy scope fails closed. Local populated-copy rehearsal and application upgrade through 0067 passed. | Production rehearsal/deployment and live scope evidence. An in-flight page cannot be recalled. |
| G2/G3 | Canonical, exact-document exporters; migration 0062 document dates; transactional producers on consultation closure, finalized prescriptions, lab verification/amendment, imaging sign-off and discharge. Admin reconciliation previews explicit existing canonical context IDs and only fills a missing verified date. Follow-up CLI creates explicitly selected missing historical contexts: preview first, facility/operator-bound, source-author-preserving and all-or-nothing, with audited durable jobs. | Clinical authorship/finalization approval; approved historical manifest/execution; real workflow-generated FHIR validation. No application-data backfill was run. |
| G4 | Staff linking API and doctor document-selection UI; one link operation per HI type; separate token-generation/link callback IDs; encrypted, expiring HIP credentials; queued retries and stable idempotency keys. | Live token and grouped-link callback round trip. Account/enrolment credentials still need M1 purpose/expiry cleanup; they are not used as HIP link tokens by the new flow. |
| G5 | Migrations 0063/0064 add leased jobs and persisted receiver-encrypted pages. Polling worker, heartbeat/fencing, idempotent operator retry and separate transfer notifications. Migration 0067 adds durable HIP consent/data-request and HIU consent acknowledgements; follow-on transfer/fetch jobs wait for successful acknowledgement. Replies contain IDs/digests, not patient content. | Discovery/link/Scan-and-Share response durability and recovery after a missing/negative asynchronous fetch callback remain; full process-crash deployment rehearsal is not completed. |
| G6/G7 | Migration 0066 protected received-content store; bounded parsing; patient/context/type/date binding; encrypted content with row-bound authentication; no new plaintext clinical outbox writes. Read APIs enforce facility, requesting clinician and current permission. | Full NRCeS/terminology validation and external HIP interoperability; historical plaintext outbox remediation; approved archive/backup retention. Strict ABHA patient-identifier validation may need an agreed mapping for external HIPs using only local identifiers. |
| G8 | Partial requests included in key cleanup; scheduled expiry/content erasure; link-token expiry; request-wide revocation clears open transfer keys even without an artefact list. Late callbacks cannot reopen completed transfers or revoked/expired consent. | Worker must actually run continuously. PostgreSQL receiver-versus-reaper contention and populated restore/cleanup rehearsal still need dedicated proof. |
| G9 | `/doctor/abdm`: patient search, consent request/status, granted-data request, record viewer and document linking. `/admin/abdm-sync`: paginated delivery jobs and retry. Hosted CI now includes both pages in the role/screen matrix; 49 role/screen entries across 14 roles passed. | Browser action-level ABDM verification against a migrated application; clinical usability review. The new CI entries prove screen loading, not an external consent/data round trip. Viewer is read-only, not automatic clinical import. Only the requesting clinician can read external content. |
| G10 | HIU callback queries lock and scope correlation to the configured facility; fetched grants must match a dispatched fetch job and cannot change patient/HIU or widen the request. HIU outbound jobs refuse a different/unconfigured facility. Direct pushes remain transaction/crypto-bound. | NHA-approved ingress/source trust and actual service-to-facility mapping. Headers alone do not authenticate a gateway. Outbound routing is still a single configured HIP/HIU, not a multi-facility registry. |
| G11 | OTP completion verifies staff/facility/active-patient ownership before calling ABDM. Identity/event commit precedes local session consumption. | Mobile verification continuation; address selection/creation; account credential purpose/expiry; persisted Scan-and-Share reception queue; checklist-confirmed profile/card scope and browser tests. |
| G12/G13 | No claim of external closure. Existing OTP relay adapter and FHIR tooling remain available. | Authorized participant, approved SMS relay, assigned checklist/HI types, registry and clinical approvals, live M1/M2/M3 evidence and NHA assessment. |

### Document contract now enforced

| Canonical reference | Exported content | Publication/date rule in the current schema |
|---|---|---|
| `encounter/<UUID>` | That consultation's complaint, diagnoses, recorded observations and SOAP note; no other encounter's records or sibling prescriptions/reports | Encounter must have `ended_at`; that is its document date. |
| `prescription/<UUID>` | Items belonging to that exact prescription only | Its encounter must be closed; date is the later of prescription creation and encounter closure. There is no independent prescription sign-off field yet. |
| `lab-result/<UUID>` | That exact current final/corrected result version | `updated_at`, because verification changes the preliminary row to final in place. |
| `radiology-report/<UUID>` | That exact current final/corrected report version | `created_at`, because sign-off creates a new version. The existing imaging builder still requires a PACS study UID. |
| `discharge/<UUID>` | That discharge's recorded summary, not all visit encounters | Non-empty summary and `discharged_at`; no unrelated OPD encounter is required. |
| `wellness/<UUID>` | Measurements from that closed encounter, no later than closure | Encounter `ended_at`; no other encounter's measurements. |

This is source selection, **not an immutable clinical archive or new signature
system**. Transfers now freeze receiver-encrypted pages before the first push,
so a retry cannot silently rebuild different clinical content. This is not a
snapshot at clinical sign-off: mutable notes/items before the first transfer
still require a clinical version/finalization decision. The exporter uses the recorded source author
and requires a registration number; it does not substitute a different doctor.
The lab schema has no separate verifier identity, and a discharge may be recorded
by a nurse without practitioner registration. Those cases need an explicit
clinical authorship/sign-off solution, not invented registration data. Registry
fields being populated does not prove that their values are verified.

### Verification actually run

- **1,490 backend tests + 14 script tests passed** in the latest `make test-pg`
  run on 9 September. The isolated **healthdoc_test** schema is at `0067`.
  The suite mixes SQLite unit fixtures and real PostgreSQL tests; it is
  not accurate to call every test a PostgreSQL test. New real-PG tests prove
  competing claims, `SKIP LOCKED`, duplicate enqueue and stale-worker fencing.
- The full gate includes durable acknowledgement/retry/fetch-correlation tests.
  Four existing Pydantic alias warnings remain.
- Historical registration adds **45 regressions**, including three real-PG tests
  for observed lock contention, all-or-nothing savepoint rollback and CLI
  rollback after a simulated commit failure. All six canonical reference kinds
  are covered. No historical application records or live gateway were used.
- The latest full run includes the final lock-order and two PostgreSQL
  reply-reservation/rollback regressions (previously verified in a 46-test run).
- Frontend at merged PR #537: **34 tests**, typecheck and production build passed.
  The latest contract run matched **205 API calls**. Hosted browser CI passed
  **49 role/screen entries across 14 roles**: the doctor ABDM page had 2/2
  responses and the admin ABDM page 3/3, with zero failed requests. These new
  entries are screen-load evidence, not action-level M1/M2/M3 evidence.
- Mutation check: changing only the prescription selector to an encounter-wide
  selector in an isolated Python process makes the new regression fail. Source
  files and the running app were not modified for this mutation.
- A second mutation check replaces fresh source reads with cached ORM reads in
  an isolated Python process: all three reopen/amendment regressions fail as
  expected. Normal tests pass. No source files were changed by the mutation.
- Ruff passes on changed ABDM modules/tests/migration-version files;
  `git diff --check` passes. A broader lint of touched legacy clinical modules
  still reports existing FastAPI-default/exception-style findings, so this is
  **not** a whole-backend lint-clean claim.
- The historical follow-up's five Python files pass Ruff; its three non-test
  Python files pass the explicit PR scan with zero blockers/warnings. No schema,
  route or frontend changes are introduced by that follow-up.
- Migration integrity: **74 migrations, linear chain, head 0067**. The explicit
  PR convention scan includes uncommitted files and reports no blockers;
  callback/OTP idempotency-convention warnings remain. The default PR scan says
  “no python files to check” and is not evidence about this uncommitted work.
- Approved local application upgrade **0060 → 0067** completed after a restricted
  backup and populated disposable-copy rehearsal. SHA-256/row-count comparisons
  over every original column matched **121 tables / 10,912 rows** after restore,
  clone upgrade and application upgrade. Backup retained; disposable clone removed.
  New job/reply tables were empty. No delivery worker, real OTP or clinical
  transfer was initiated. This is not production or certification evidence.
- Browser recheck reached the Keycloak sign-in screen without a certificate
  warning. The test-account sign-in attempt timed out, and the next read was
  blocked by the approval service's usage limit. No sign-in or workflow success
  is claimed. Application-migration approval was subsequently received and applied.

### Deployment and next work

Do not deploy these ORM changes without rehearsing and applying migrations **0061
through 0067**. Existing contexts deliberately keep NULL `document_at` and disappear
from shareable discovery until reconciled to verified source records. Existing
requests with NULL original scope need a fresh external request; **do not fill
them from the broader grant**. Do not blindly downgrade after adopting these
fields, because downgrade discards their scope metadata.

The original `scripts/maintenance/backfill_care_contexts.py` was privately
archived and replaced, not executed. Its replacement requires explicit records,
facility and operator, previews by default, and rejects an entire batch when a
record is refused. It preserves source authors, writes source-derived dates and
queues notification jobs without sending HTTP or creating links.
See [historical registration runbook](abdm-historical-backfill.md).
Application-data execution and starting delivery still need separate approval.

Next implementation sequence: (1) M1 continuation and credential lifecycle,
then the persisted Scan-and-Share reception workflow; (2) durable remaining
discovery/link/profile replies and asynchronous callback timeout recovery;
(3) clinical source/version and
historical-content remediation; (4) browser/worker recovery runs against the now
migrated local application and a separate production rehearsal; (5) real participant/ingress evidence against the assigned
NHA checklist. The last two steps need the external inputs described above.
See [local verification and recovery runbook](abdm-local-verification-and-recovery.md).
**M1–M3 remain not certification-ready.**

## 1. Decision summary

**Keep HealthDoc's v3 integration and complete its missing workflows. Do not replace it with the cloned Bahmni services.** Bahmni is a useful reference for how hospital records become shareable and how received records become usable by a doctor. Its India integration clones, however, use older gateway and ABHA APIs.

HealthDoc is not starting M1–M3 from zero. Its outbound calls, official callback routes, nested payload models, OTP workflows, consent services, encryption and clinical bundle builder exist. The remaining work is partly missing product functionality and partly correctness/security defects in the connections between those components.

The most important findings are:

1. **M2 loses the requested transfer date range between callback and worker.** The callback validates it, but the request row does not store it; the worker selects using the wider consent artefact range.
2. **Care-context creation is still disconnected from normal clinical completion.** The new, uncommitted backfill script helps only consultations and prescriptions, and its record-level references do not match the worker's visit-wide selection.
3. **HIP-initiated linking has no application caller for token generation.** The callback also overwrites one correlation ID when linking multiple HI-type groups.
4. **M3 cannot yet provide a complete clinical viewing journey.** The frontend does not call the HIU API; decrypted bundles go into a general-purpose outbox, not a consent-controlled clinical record store/viewer.
5. **Revocation/expiry and received-content validation need strengthening.** Partially received requests are missed by key cleanup; inbound content is checked as a document Bundle, not fully bound to the consent's patient, care contexts, types and dates.
6. **M1 has a usable starting workflow, not all Bahmni-equivalent flows.** Mobile continuation, ABHA address management and card workflows are missing. Scan-and-Share has a callback, but its token is derived from the UHID rather than a persisted registration queue entry.

These are source-level findings, not evidence of a real patient-data incident. Details, affected files and acceptance tests follow.

### Updated public endpoint observation

Read-only checks during this review produced:

| Request | Result | What it establishes |
|---|---|---|
| GET `https://abdm.healthdoc.world/api/v1/health` | HTTP 404, empty body | This URL does not currently provide a usable public health check. |
| GET `https://abdm.healthdoc.world/api/v3/hip/patient/share` | HTTP 405 | The public path responds as a POST-only resource would. |
| GET `https://abdm.healthdoc.world/api/v3/hiu/health-information/transfer` | HTTP 405 | The public path responds as a POST-only resource would. |

**Yesterday's blanket tunnel-outage finding should not be repeated as today's fact.** These checks indicate routing progress, but do not prove callback authentication, the deployed commit, database readiness, OTP delivery or a successful NHA exchange. No callback POST, OTP request or patient-data transfer was performed in this review.

## 2. What was inspected, and what this report does not claim

Inventoried all 23 local repositories: 8 in `BahmniIndiaDistro`, 15 in `Bahmni`. Traced the ABDM-facing code in the India distribution, checked the main Bahmni distribution/frontend relationship, compared HealthDoc's current implementation and supplied Postman collections, and checked public primary sources.

This is an ABDM architecture and source review, not a line-by-line security audit of every Bahmni module. Bahmni was not started, its suites were not executed, and HealthDoc's full backend/browser suites were not rerun. No historical certificate is being treated as proof that these exact clones pass the current sandbox.

### India integration repositories

| Repository | Local HEAD / commit date | Role in the implementation |
|---|---|---|
| `ABHA-Verification` | `de1f6e6` / 2024-06-19 | React identity creation, verification, mobile/address/card screens and patient matching. |
| `hip-service` | `764e19e` / 2024-12-13 | C# gateway-facing HIP, identity adapters, linking, consent, encrypted transfer. |
| `openmrs-module-hip` | `a1bb65e` / 2025-01-21 | Java adapter from actual OpenMRS patients/visits/clinical records to care contexts and FHIR documents. |
| `hip-atomfeed-listener` | `327ff02` / 2025-02-05 | Reacts to clinical encounter events and requests new-context handling/notifications. |
| `health-information-user` | `86a5751` / 2024-06-21 | Java consent requests, callback processing, data retrieval/storage and access APIs. |
| `hiu-ui` | `0276cb0` / 2024-10-09 | Clinician consent-request and received-health-information interface. |
| `hiu-db-initializer` | `3a52b99` / 2025-03-12 | HIU database initialization/migrations; not an independent milestone implementation. |
| `bahmni-india-package` | `9dfb03c` / 2024-05-24 | Compose wiring for EMR plus HIP, HIU, UI, PostgreSQL, RabbitMQ, OTP and atomfeed services. |

The remaining `Bahmni` repositories provide the hospital application and supporting modules, not another complete M1–M3 implementation. Their inventory is in Appendix A. The India package explicitly composes extra ABDM services and uses India-specific OpenMRS/proxy images; cloning the latest main Bahmni frontend is not equivalent to installing that integrated distribution. See [India Compose](</Users/ritikkumar/Desktop/BahmniIndiaDistro/bahmni-india-package/docker-compose.yml:135>).

## 3. How Bahmni obtained its integration status

There is credible historical evidence, but the dates need careful attribution:

- Bahmni's project page records all three milestones completed on **9 November 2021**, and says the project demonstrated functional compatibility through the sandbox and passed WASA. This is Bahmni's own account. [Bahmni project record](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/2901114904)
- The Government of India's **8 February 2022** release lists **Bahmni by Thoughtworks Technologies** among products whose partners received ABDM-integrated certificates/logos. The release does not reproduce Bahmni's individual certificate or enumerate its three levels. [MoHFW/PIB announcement](https://www.pib.gov.in/PressReleasePage.aspx?PRID=1796553)
- A later Bahmni deployment guide states certification on **15 February 2022**. That differs from the earlier government announcement; these sources do not establish a single unambiguous certificate-issuance date. [Bahmni deployment guide](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/3148087297)

The practical lesson is that they delivered and demonstrated complete user/data flows, not merely a session-token endpoint. HealthDoc must obtain its own validation/approval; copying code or using a previously integrated project's design does not transfer approval.

The current NHA sandbox documentation and partner/checklist links were not fully readable without their JavaScript application. **The exact checklist assigned to HealthDoc, its required HI types, current security evidence and evaluation appointment must be confirmed in the authenticated portal or with NHA.** Do not treat a 2021 scope or this engineering report as the current certification checklist. [NHA v3 documentation](https://sandbox.abdm.gov.in/sandbox/v3/new-documentation?doc=WorkingWithABDMapi)

## 4. How their M1 works

### Implemented chain in the cloned code

```text
Reception / ABHA React extension
  → identity creation or existing-identity verification
  → HIP service calls ABDM identity APIs
  → OTP / mobile continuation / ABHA address / card
  → compare returned demographics with existing OpenMRS patients
  → selected existing patient or new patient data returned to host application
```

The clone contains explicit screens for Aadhaar consent, Aadhaar OTP, mobile verification, creating/linking an ABHA address, existing-identity verification and an ABHA card. It does not stop at displaying an HTTP success response.

Evidence:

- [Identity API paths](</Users/ritikkumar/Desktop/BahmniIndiaDistro/ABHA-Verification/src/api/constants.js:19>) include mobile verification, profile/address and card operations.
- [Identity API adapter](</Users/ritikkumar/Desktop/BahmniIndiaDistro/ABHA-Verification/src/api/hipServiceApi.js:206>) sends the requests to the HIP service.
- [Patient selection/return](</Users/ritikkumar/Desktop/BahmniIndiaDistro/ABHA-Verification/src/components/patient-details/patientDetails.jsx:68>) builds ABHA number/address identifiers and returns selected patient data to the embedding application.
- [ABHA card screen](</Users/ritikkumar/Desktop/BahmniIndiaDistro/ABHA-Verification/src/components/creation/ABHACard.jsx:18>) fetches, displays and downloads a card.

The historical Bahmni project description used a redirected/modal creation flow; the later clone contains more custom creation screens. Do not assume every screen present in 2024 was part of the 2021 evaluation. [Historical M1 scope](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/2901114904)

### HealthDoc comparison

HealthDoc already has receptionist-facing existing-ABHA OTP and Aadhaar-enrolment flows, a server-side OTP transaction lifecycle, encrypted identity credential storage and duplicate identity safeguards. These are real implementation assets to keep. See [ABHA panel](../frontend/src/features/receptionist/AbhaIdentityPanel.tsx), [API adapter](../frontend/src/features/receptionist/api.ts), [identity service](../backend/app/integrations/abdm/identity/service.py).

Remaining M1 work:

- Implement the required continuation states, particularly separate mobile verification and ABHA address selection/creation. The service explicitly says the mobile continuation flow is reserved but not implemented.
- Add profile/card functions if they are in HealthDoc's assigned checklist. Their absence is established; their mandatory certification status is not assumed.
- Keep credentials distinct: a gateway access token, an ABHA account/enrolment token and a HIP `X-LINK-TOKEN` are not interchangeable. The identity service calls a returned account token `linking_token`; the M2 helper expects a token arriving asynchronously from HIP token generation. Rename/model these accurately with purpose and expiry rather than using the stored M1 value as an M2 shortcut.
- Complete Scan-and-Share as a real reception flow. The callback exists and creates/matches patients, but its acknowledgement token comes from splitting the UHID; it does not persist a corresponding registration queue entry. Use an idempotent, facility/counter-scoped queue ticket and display it to reception. See [profile-share handler](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:453>) and [token generation](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:585>).
- Record actual successful and unsuccessful sandbox OTP attempts with an authorized tester and redacted evidence. Unit tests are not proof of SMS delivery or NHA acceptance.

## 5. How their M2 works

```text
Clinical encounter / visit in OpenMRS
  → atomfeed listener
  → visit care-context adapter
  → HIP add/link context + new-record notification
  → patient discovery/link proof and consent
  → HIP data-request processing queue
  → fetch clinical FHIR from OpenMRS HIP module
  → encrypt for the HIU → direct data push → notify gateway
```

### The important implementation choices

**A. Clinical events drive integration.** `EncounterFeedWorker.process()` loads an encounter, applies configured exclusions, then calls `HipFeedIntegrationService.processEncounter()`. That resolves care contexts by patient and visit and invokes new-context and SMS handling. This is the architectural connection HealthDoc is missing—not a requirement to adopt Java or AtomFeed. [Encounter worker](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-atomfeed-listener/hip-atomfeed/src/main/java/org/bahmni/module/hipfeedintegration/atomfeed/worker/EncounterFeedWorker.java:39>), [event-to-HIP service](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-atomfeed-listener/hip-atomfeed/src/main/java/org/bahmni/module/hipfeedintegration/services/HipFeedIntegrationService.java:26>).

**B. The context and document use a consistent visit identity.** The OpenMRS adapter queries care contexts for a specific visit. Its prescription bundle includes the encounter's visit UUID as its context reference. [Care-context adapter](</Users/ritikkumar/Desktop/BahmniIndiaDistro/openmrs-module-hip/api/src/main/java/org/bahmni/module/hip/service/impl/CareContextServiceImpl.java:47>), [prescription builder](</Users/ritikkumar/Desktop/BahmniIndiaDistro/openmrs-module-hip/api/src/main/java/org/bahmni/module/hip/builder/FhirBundledPrescriptionBuilder.java:30>).

**C. Clinical mapping is a separate subsystem.** The module has dedicated builders/services for Prescription, DiagnosticReport, OPConsultation, DischargeSummary, ImmunizationRecord, WellnessRecord and HealthDocumentRecord. The surrounding hospital modules supply facts; the gateway adapter does not manufacture a generic JSON report. Inspect the [builder directory](</Users/ritikkumar/Desktop/BahmniIndiaDistro/openmrs-module-hip/api/src/main/java/org/bahmni/module/hip/builder>) and [clinical service implementations](</Users/ritikkumar/Desktop/BahmniIndiaDistro/openmrs-module-hip/api/src/main/java/org/bahmni/module/hip/service/impl>).

**D. Transfer processing is separated from the HTTP request.** A RabbitMQ listener receives work, the handler collects records and creates encrypted entries, and a client pushes to the HIU and sends gateway status. However, the clone has reliability defects described in section 8; the presence of RabbitMQ is not proof of safe delivery. [Queue listener](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/DataFlow/MessagingQueueListener.cs:27>), [transfer handler](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/DataFlow/DataFlowMessageHandler.cs:24>).

### HealthDoc comparison

Already present: official discovery/init/confirm callbacks, mediated OTP proof, care-context APIs, link/consent storage, outbound acknowledgement/notification calls, consent/context filtering, FHIR construction, ECDH encryption and an HTTP transfer worker. The earlier statement that there is no transfer worker is now outdated.

Current advertised/buildable HI types are **five**, not six: `OPConsultation`, `Prescription`, `DiagnosticReport`, `DischargeSummary`, `WellnessRecord`. ImmunizationRecord, HealthDocumentRecord and Invoice are intentionally rejected until supported. Six sample documents or a previous report count must not be presented as six supported types. See [builder vocabulary](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/fhir/builder.py:31>) and [outbound vocabulary](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/gateway.py:49>).

The detailed M2 defects and fixes are in section 7. Most urgently: preserve the exact request scope, make context semantics consistent, add an event producer, finish HIP-initiated linking and make transfers/notifications recoverable after a process restart.

## 6. How their M3 works

```text
Clinician HIU screen: patient + purpose + HI types + period + access expiry
  → consent request to consent manager
  → patient grants / denies / revokes
  → fetch artefact and request health information
  → HIP pushes encrypted records to HIU
  → process/store records and expose authenticated read APIs
  → clinician views records grouped by date and source HIP
  → consent status/expiry gates access and deletion processing
```

Bahmni's important addition over an API-only implementation is a **usable recipient application**:

- [Consent creation UI API](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hiu-ui/src/redux/apiCalls/createConsentApi.js:4>) sends selected types, purpose, dates and `dataEraseAt`.
- [Grant processing](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/consent/GrantedConsentTask.java:36>) correlates and fetches consent artefacts.
- [Health-information read controller](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/dataflow/HealthInfoController.java:42>) exposes received information to the authenticated caller.
- Its single-consent reader checks requester, granted status and expiry before returning data. This is a specific inspected path, not a claim that every alternate attachment/bulk path is equally correct. [Read-time checks](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/dataflow/HealthInfoManager.java:55>).
- [UI record loading](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hiu-ui/src/redux/apiCalls/loadHealthDataApi.js:4>), [date/source display](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hiu-ui/src/components/HealthInformation/HealthInformation.view.js:5>) and [FHIR reference processing](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hiu-ui/src/components/common/HealthInfo/FhirResourceProcessors.js:54>) turn the bundle into something a clinician can inspect.
- Revocation changes consent state and publishes follow-up processing; a deletion listener removes stored health information and files. This is useful lifecycle architecture, not an audited guarantee about every deletion case. [Revocation task](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/consent/RevokedConsentTask.java:38>), [deletion listener](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/dataflow/DataFlowDeleteListener.java:56>).

HealthDoc already sends consent and HI requests and handles official consent/data callbacks. But it lacks the clinician request/status/record-viewing journey and a dedicated consent-governed content store. Its receipt table retains metadata/hash only; decrypted content is copied into an ordinary JSONB outbox event. No application consumer for that event was found. See [HIU API](../backend/app/integrations/abdm/hiu/router.py), [receiver](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:984>) and [outbox insertion](</Users/ritikkumar/Desktop/healthdoc/backend/app/outbox/service.py:28>).

## 7. HealthDoc gaps and exact resolution work

Priority definitions: **P0** = correctness/privacy blocker before real clinical exchange; **P1** = missing end-to-end functionality/recovery; **P2** = checklist-dependent scope or final operational evidence. These are engineering priorities, not NHA-issued severity ratings.

### G1 — P0: request date range is validated, then discarded

Evidence chain: [callback validates `hiRequest.dateRange`](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:669>) → [request model has no requested-range columns](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/models.py:184>) → [worker passes the artefact range back into authorization](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/worker.py:494>).

Consequently, if the grant covers January–March but the data request asks only for February, worker selection can expand back to January–March. This is a source-confirmed loss of scope; actual over-transfer was not executed.

Fix: persist the requested/effective interval and selected scope on the request/job, revalidate against the current artefact before each delivery, and never widen it during retry. Add a migration rather than hiding the fields in unrelated metadata.

Acceptance: a three-month grant plus one-month request exports only the requested month; worker restart preserves it; narrower/changed/revoked consent cannot expand data selection.

### G2 — P0: record-level backfill references feed a visit-wide exporter

The new [backfill script](../scripts/maintenance/backfill_care_contexts.py) creates `encounter/<id>` and `prescription/<id>` contexts. The [worker](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/worker.py:111>) does not resolve those identifiers: it loads every encounter and prescription associated with the context's visit. The [context selection gate](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/service.py:260>) filters by visit date, not individual clinical document dates.

Risk: a context that appears to identify one prescription can serialize other prescriptions from the same visit; backfilling multiple contexts can repeat the same visit-wide content. Long visits also need explicit date semantics. This should be resolved before running the new backfill against important data.

Fix: choose and document either visit-level contexts with deliberately visit-level content, or document/encounter-level contexts with typed source IDs and exact queries. Enforce finalization/version rules and clinical date selection. Give the backfill an explicit authorized actor/facility scope; it currently selects the first user for attribution. Keep a dry-run/count mode and add tests before using it.

Acceptance: two prescriptions/encounters in one visit produce exactly the intended content for each consented context; drafts and out-of-scope records are excluded; reruns do not duplicate records or context identities.

### G3 — P1: no automatic care-context producer

The normal app's only `AbdmCareContext(...)` creation is the manual HIP API; the additional producer is the untracked backfill. That script covers only consultation/prescription and deliberately does not notify ABDM. It is a stopgap, not a complete M2 workflow.

Fix: emit a durable event in the same transaction as the relevant clinical finalization/release, then idempotently create/update the correct context. Link new contexts and notify only when the necessary patient/link state permits it. Cover all five supported types according to the chosen clinical context model.

Acceptance: complete a normal consultation, release a diagnostic report and sign a discharge; contexts appear without a maintenance script. After initial patient linking, new records become visible in the PHR through the proper link/notify chain.

### G4 — P1: HIP-initiated token flow is not started; multi-type correlation is lossy

AST inspection found **zero production callers** of [generate_link_token](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/gateway.py:177>). Meanwhile [on-token](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:370>) requires an already-pending link matching `response.requestId`. Inside its HI-type loop, each outbound request replaces the same `link.gateway_request_id`; only the final group remains addressable by the [on-carecontext handler](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:412>).

Fix: add a facility-scoped initiating service/API/UI, persist correlation before dispatch, securely manage the genuine HIP link token and expiry, and keep one child operation per outbound group/request. Confirm only the contexts acknowledged successfully; do not mark the entire group set confirmed after just the last callback.

Acceptance: link Prescription and OPConsultation together, reverse callback order, fail one group, replay the other and restart the app. Each context retains its own truthful state. An M1 account token must not substitute for the HIP link token.

### G5 — P1: transfer/notification execution is not durably scheduled

The callback commits a row and launches [FastAPI BackgroundTasks](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:704>). A duplicate transaction returns before re-enqueueing it. A process exit after acceptance can strand the transfer. The worker records a failed final gateway notification, but no dedicated reconciliation consumer was found. See [delivery/notification handling](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/worker.py:547>).

Fix: use a durable job/outbox with leases, backoff, per-page progress, bounded retries, dead letters and operator retry. Commit the immutable selected document/version or protected snapshot so a retry cannot silently change clinical content. Track HIU delivery separately from gateway notification. HealthDoc already has an outbox claim/reaper implementation; extend it with a real ABDM handler rather than introducing RabbitMQ solely because Bahmni uses it.

Acceptance: terminate a dedicated test worker after HTTP acceptance and between pages; work resumes without lost transactions or contradictory status. A gateway-notification outage retries the notification, not an already delivered clinical transfer.

### G6 — P0: received records have no dedicated protected storage/retention lifecycle

The receiver places `json.loads(plaintext)` in an outbox payload with `sensitivity="critical"`. [The outbox service](</Users/ritikkumar/Desktop/healthdoc/backend/app/outbox/service.py:28>) serializes ordinary JSONB; the sensitivity label does not itself encrypt it or enforce consent expiry. This is application-level plaintext storage, irrespective of any disk/database encryption below the app.

Fix: persist validated received documents in a dedicated encrypted store associated with facility, patient, consent artefact, source HIP, transaction, context, content hash and permitted lifetime. Keep only identifiers/minimal metadata in the outbox. Deny access when consent expires/revokes and apply an approved deletion/retention policy to content, caches, exported copies and recoverable backups. Retain minimal audit evidence separately; do not guess legal retention periods or silently delete statutory clinical records.

Acceptance: received health content is not readable from general event payloads; a doctor can view only an authorized patient's current permitted records; revoke/expiry blocks subsequent reads/downloads and scheduled cleanup survives restart.

### G7 — P0: incoming content is not fully bound to the grant

[receive_bundle](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hiu/service.py:300>) checks cryptographic decryption, checksum, media and `Bundle`/`document` shape. It does not compare the bundle patient, HI type, clinical dates and claimed context with the consent scope. The outer receiver checks consent status/expiry, but does not perform those content-level checks either.

Fix: validate allowed care-context reference, expected patient/ABHA binding, claimed source and supported HI type; perform structural/profile validation and clinically appropriate date checks before making data viewable. Quarantine unknown/invalid content with minimal redacted diagnostics. Authenticated encryption is not, by itself, proof that an arbitrary declared sender or patient identity is correct.

Acceptance: well-encrypted but wrong-patient, unconsented-context, unsupported-type, malformed-reference and out-of-window bundles are not accepted as usable clinical records.

### G8 — P0: revocation cleanup excludes partial transfers

[_expire_open_requests](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hiu/service.py:178>) selects `requested` and `acknowledged`, but the receiver moves active multi-page transfers to `partial`. Thus a revoked partial request retains encrypted private-key material. The receiver still checks revocation before accepting more data, so this is not evidence that revocation permits further reads; it is a key-lifecycle defect. No scheduled expiry cleanup was found.

Fix: include every non-terminal state, synchronize cleanup with in-flight processing, and add scheduled expiry/recovery cleanup. Address the protected content lifecycle in G6 as well—dropping a transport key does not remove already decrypted copies.

Acceptance: revoke after page one of two; remaining pages are refused, key material is cleared, and already received content follows the approved policy. Expiry without a subsequent request also triggers cleanup.

### G9 — P1: clinician M3 request/status/viewing journey is missing

No frontend caller of `/abdm/hiu` was found. Backend routes create requests, list a request's artefacts and request health information, but there is no complete list/detail/status-and-received-record UI. An admin ABHA-link screen is not an HIU clinical workspace.

Fix: add doctor-facing consent request, consent/status tracking, permitted-data fetch and read-only external-record viewing within the existing design system. Supply facility/patient-scoped list/detail APIs, safe paging, denied/revoked/expired/partial/error states and audit events. Start with provenance-preserving viewing; automatic import into local prescriptions/diagnoses is a separate clinical decision.

Acceptance: a doctor requests outside records, the patient grants less than requested, the doctor sees only the granted data with source/date/version, and subsequent revocation blocks viewing. A second facility and an unauthorized role cannot enumerate these records.

### G10 — P0/P1: callback trust and facility routing require deployment proof

Official routes no longer require the private `X-HealthDoc-Callback-Secret`; that requirement applies to legacy private callbacks. Current [official callback checks](../backend/app/integrations/abdm/callback_auth.py) validate routing metadata, time and replay handling, but explicitly do not claim cryptographic origin authentication. Recipient headers are spoofable outside a trusted ingress boundary.

Fix: confirm the current supported NHA callback-authentication/ingress arrangement and configure it at the deployment boundary. Verify any supported signed identity against its proper issuer/keys/audience; otherwise establish the approved source restrictions without inventing an undocumented shared-secret requirement. Keep direct external HIP→HIU push separate from gateway callbacks. Add body/entry size limits and abuse controls compatible with valid encrypted transfers.

[_facility_id](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/external_router.py:82>) currently resolves one configured HFR identifier. That may suit a declared single-facility sandbox demo; it is not multi-facility service routing. Verify the actual HIP/HIU service→facility/HFR mapping and practitioner registration data. A placeholder that satisfies a database field is not evidence of registry registration.

Acceptance: a legitimate external callback/push works; forged recipient metadata, unknown transactions, cross-facility routing and replay do not create usable clinical data. Record which deployment/commit was tested.

### G11 — P1/P2: complete the remaining M1 workflows to the assigned checklist

Implement the M1 gaps described in section 4. Keep unauthorized/ambiguous identities unlinked, with clear recovery UI. Separate card/profile/account features from HIE consent/link operations. Do not add face authentication, Scan-and-Pay, every PHR endpoint or immunization merely because a collection/repository includes them; first confirm the required product scope.

Acceptance: receptionist browser evidence for each required creation/verification path, retry/expiry and duplicate-patient outcome; real Scan-and-Share tickets if in scope; no OTP/Aadhaar/token in logs or screenshots.

### G12 — P1: patient-initiated link OTP delivery must actually work

The [link OTP service](</Users/ritikkumar/Desktop/healthdoc/backend/app/integrations/abdm/hip/link_otp.py:62>) refuses delivery when its relay URL is absent. Its Redis digest/TTL/attempt handling exists, but no SMS was sent in this review and current deployment credentials were not printed or assumed valid.

Fix: configure an authorized relay/test delivery arrangement that matches the service contract. Prove delivery, timeout, bounded attempts and recovery. Do not bypass proof with a hardcoded OTP or log the code for a demo.

Acceptance: the PHR-driven link-init flow reaches the tester's approved destination; only the correct unexpired OTP confirms the selected contexts.

### G13 — P1/P2: clinical validation and external evidence are still required

The published NRCeS guide currently identifies **FHIR R4, IG 6.5.0**. Confirm the version NHA expects for HealthDoc's evaluation and pin it in validation tooling. Validate the actual documents generated from the clinical workflow, not only example bundles. [NRCeS published guide](https://nrces.in/ndhm/fhir/r4/index.html)

Acceptance: exported-and-received documents for each declared HI type pass the assigned profile/terminology checks, contain the correct clinical facts and resolve internal references. Record redacted request/transaction/consent IDs, actual observed outcomes and external participant evidence. Passing two HealthDoc instances against each other alone can hide shared protocol errors; include an NHA-approved/reference external HIP/HIU or PHR.

## 8. What not to copy from Bahmni

The clones are useful, but this review found reasons not to treat them as a ready-made v3 replacement:

| Finding in the clone | Consequence for HealthDoc |
|---|---|
| HIP constants use `v0.5` gateway paths; identity UI includes v1/v2 paths; HIU callback constants use `/v0.5`. | Reuse the workflow design, not those URLs/payloads. Keep HealthDoc's supplied v3 contracts. [HIP constants](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/Common/Constants.cs:5>), [HIU constants](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/common/Constants.java:5>). |
| HIP `DataFlowClient` initializes success and never checks a non-2xx HTTP response; the TODO explicitly notes it. | A rejected push can be reported delivered. Preserve HealthDoc's HTTP failure checking and add external rejection tests. [Transfer client](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/DataFlow/DataFlowClient.cs:50>). |
| Rabbit queue declaration is durable but also exclusive; handler invokes an asynchronous send through `MatchSome`. | Do not infer restart safety or correct acknowledgement ordering from RabbitMQ's presence. Review/retest these semantics before reuse. [Queue declaration](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/DataFlow/MessagingQueueListener.cs:31>), [handler](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-service/src/In.ProjectEKA.HipService/DataFlow/DataFlowMessageHandler.cs:28>). |
| Atomfeed new-context condition calls `.equals()` on `getHealthId()` before checking it for null. | A genuinely null ID can throw; use this as a regression case, not a copied guard. [Event integration](</Users/ritikkumar/Desktop/BahmniIndiaDistro/hip-atomfeed-listener/hip-atomfeed/src/main/java/org/bahmni/module/hipfeedintegration/services/HipFeedIntegrationService.java:39>). |
| Identity extension sends patient data to `window.parent` with target origin `"*"`. | Use an explicit trusted origin if implementing an embedded flow. [Patient handoff](</Users/ritikkumar/Desktop/BahmniIndiaDistro/ABHA-Verification/src/components/patient-details/patientDetails.jsx:94>). |
| Older HIU security differentiates gateway JWT/JWK verification from direct data push. Its token verifier also logs a malformed token value on one failure branch. | Copy neither the historical auth assumptions nor credential-bearing logging. Obtain today's NHA contract and keep secrets out of logs. [Security routing](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/SecurityConfiguration.java:61>), [token verifier](</Users/ritikkumar/Desktop/BahmniIndiaDistro/health-information-user/src/main/java/in/org/projecteka/hiu/common/GatewayTokenVerifier.java:38>). |

These are source findings, not reproduced attacks or claims about Bahmni's current hosted deployments. No code was copied. Any later reuse requires component-specific license/attribution review.

## 9. Immediate work plan

Do not spend the first day migrating to Bahmni or changing HealthDoc's technology stack. Use the following work packages, with small independently reviewable changes routed through staging.

| Order / owner | Work package | Definition of done |
|---|---|---|
| 0 — Product + NHA contact + DevOps | Get assigned case list/HI types; verify public ingress, HIP/HIU identities, OTP destination/relay, HFR/practitioner data and evaluation process. | Required inputs are written down without secrets; a controlled valid callback reaches the intended deployed revision. |
| 1 — Backend + clinical reviewer | G1/G2/G7: persist transfer scope, align care-context granularity and reject mismatched incoming content. | Positive and negative scope/content regression tests pass. |
| 2 — Backend | G3/G4: clinical event producer and fully correlated HIP-initiated link flow. | A real finalized record links and appears outside HealthDoc; multi-type partial/reordered callbacks are correct. |
| 3 — Backend + DevOps | G5/G6/G8: durable jobs, encrypted received-record storage, revoke/expiry lifecycle. | Restart, retry, page duplication, revoke-mid-transfer and expiry-without-traffic tests pass. |
| 4 — Frontend + backend | G9: clinician HIU request/status/viewing. | Browser journey ends with readable external records and then demonstrates loss of access on revocation. |
| 5 — Frontend + identity backend | G11/G12: required M1 continuations, real scan queue, OTP delivery. | Assigned M1 flows work with authorized testers, including error paths. |
| 6 — QA + clinical/security reviewers | G10/G13: external interoperability, actual FHIR validation, security evidence and recordings. | Evidence is mapped to every assigned case; remaining exceptions are explicit. |

Suggested implementation boundaries: separate changes for (a) transfer scope/context model, (b) linking/event production, (c) received-content security/lifecycle, (d) HIU UI, and (e) remaining M1 UI. Migrations and tests belong with the feature they protect. This report does not authorize merging or deploying those changes.

### Practical time expectation

These are planning estimates, not measured delivery promises. With **two experienced backend engineers, one frontend engineer, and a QA/DevOps person available daily**, and no waiting for sandbox access:

- First day: establish required scope and ingress, reproduce/fix the highest-risk selection/lifecycle defects, and attempt the existing narrow M1 OTP path with an authorized tester.
- Approximately **5–8 working days**: a focused, externally exercised M1–M3 pilot across the already-supported HI types, assuming the clinical context decision is made promptly.
- Approximately **8–12 working days**: a more defensible engineering handoff including missing identity branches, durable recovery, lifecycle negatives and review rework.
- A single engineer should budget roughly **2–3 weeks**, with substantial uncertainty from clinical mapping and external interoperability failures.

NHA review, required security assessment/clearance, appointments and credential provisioning are **additional external lead time**. Completion of all three certifications tomorrow is not a credible commitment from this baseline. A verified narrow milestone demonstration is a different target from full approval.

## 10. Milestone demonstration and evidence checklist

This is an engineering rehearsal sequence; reconcile it with HealthDoc's actual NHA-assigned cases before claiming milestone completion.

### M1: prove identity at reception

1. Use the frozen sandbox deployment, approved tester and sandbox identity environment.
2. Create a local patient, then run existing-ABHA OTP verification and the required new-ABHA enrolment branches.
3. Complete any required mobile/address/profile/card steps rather than marking a mid-flow response as finished.
4. Show correct local-patient binding and duplicate prevention. Prove incorrect/expired OTP and ambiguous identity do not link.
5. If Scan-and-Share is required, scan the facility/counter QR in the supported sandbox PHR and show the same persisted ticket at reception and in the acknowledgement.
6. Keep redacted screenshots/outcome records. Never record Aadhaar, OTP, bearer token or secret values.

### M2: prove HealthDoc can provide records

1. Complete real clinical test records using HealthDoc's normal screens; confirm automatic context creation and precise source mapping.
2. Prove the required HIP-initiated and patient-initiated discovery/link paths. Confirm each context only after its own acknowledgement.
3. Create another finalized record after linking; prove the new link/notification makes it visible outside HealthDoc.
4. Using an approved/reference external participant, grant scoped consent and request a deliberately narrower date interval.
5. Show acknowledgement, durable transfer processing, encrypted direct push, external receipt and gateway notification.
6. Validate the actual clinical bundle for each declared HI type. Prove unlinked, revoked, expired and out-of-range requests fail safely.
7. Restart the dedicated test worker during a multi-page transfer and prove recovery without changing the selected clinical content.

### M3: prove a clinician can use outside records

1. From the doctor UI, request records from a separate/reference HIP using the tester's ABHA address, supported purpose, type selection, period and access expiry.
2. Grant a narrower scope in the PHR; fetch and store the actual artefact, then request only its permitted information.
3. Receive encrypted pages, validate/decrypt/quarantine as appropriate and persist permitted content securely.
4. Show source-labelled external records in the clinician UI, with patient, dates and provenance intact—not only a database row or Postman response.
5. Demonstrate denial, revoke after receipt, revoke mid-transfer, access expiry, wrong-patient content, duplicate pages and cross-facility denial.
6. Verify scheduled cleanup and repeat after a restart. Record final evidence against the assigned NHA case IDs.

## 11. Verification actually performed in this review

| Check | Observed result / limit |
|---|---|
| Local repo baseline inventory | 23 repositories identified; India HEADs listed above and main Bahmni HEADs below. |
| Safe supplied-collection audit | 8 collection files, 398 requests; all **23/23** configured outbound paths found. This checks path presence, not complete request/response compatibility. |
| Collection safety observation | One request points directly at a production host and one uses a legacy session path. Four environment files were not printed or executed. Do not run the complete collection blindly. |
| Collection-audit regression tests | `.venv/bin/python -m pytest scripts/tests/test_abdm_collection_audit.py -q`: **3 passed**. Initial `unittest` discovery collected zero and was not counted as a passing test gate; system Python lacked pytest, so the project environment was used. |
| Static AST call-site check | Zero production calls to `generate_link_token`; HIP request model has no persisted requested-range fields. |
| Current public routing | Health URL 404; two representative POST-only callback paths respond 405 to GET. |
| Full suites, NHA OTP/consent round trip, official FHIR validator, browser demos | **Not run in this review.** Earlier suite counts and screenshots remain historical evidence, not fresh certification proof. |

The current NHA reference repository confirms the official callback path family used by HealthDoc. It is a protocol reference, not a substitute for the assigned test checklist. [NHA GatewayURL.java](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/common/constants/GatewayURL.java)

The architecture-review skill shaped this report around complete user/data lifecycles and explicit acceptance criteria. Only this report was added: application code, configuration, databases, services and branches were not changed. The existing untracked comparison document and backfill script were preserved.

## Appendix A. Main Bahmni repository inventory

These were inventoried for distribution context. Deep M1–M3 tracing concentrated on the eight India integration repositories, not an exhaustive audit of all clinical/ERP/PACS internals.

| Repository under `/Users/ritikkumar/Desktop/Bahmni` | Local HEAD | Commit date | Relevance to this comparison |
|---|---|---|---|
| `OpenElis` | `c399016a` | 2026-06-17 | Laboratory source system. |
| `bahmni-apps-frontend` | `e9a18363` | 2026-09-08 | New main application frontend; not the India ABHA/HIU extensions. |
| `bahmni-core` | `04a5299ed` | 2026-08-27 | Hospital/OpenMRS domain services. |
| `bahmni-docker` | `c32e9a6` | 2026-08-28 | Main distribution deployment. |
| `bahmni-module-fhir2-addl-extension` | `046d889` | 2026-09-07 | Additional FHIR2 functionality; distinct from the India clinical HIP adapter. |
| `bahmni-module-immunization` | `b59b382` | 2026-09-07 | Immunization source workflow. |
| `bahmni-odoo-modules` | `c7bfa18` | 2026-07-16 | ERP/billing/inventory integration. |
| `bahmni-reports` | `5b7f95b` | 2026-09-03 | Reporting. |
| `openerp-atomfeed-service` | `6c4f271` | 2025-12-16 | ERP event integration, not the HIP atomfeed listener. |
| `openmrs-distro-bahmni` | `07bb267` | 2026-08-27 | OpenMRS distribution assembly. |
| `openmrs-module-bahmniapps` | `24ec65d9a` | 2026-08-27 | Main/legacy Bahmni UI. |
| `openmrs-module-ipd` | `f3eeb65` | 2026-08-28 | Inpatient source workflows. |
| `openmrs-module-ipd-frontend` | `4b25c43` | 2026-09-03 | Inpatient UI. |
| `pacs-integration` | `a53015c` | 2026-07-16 | Imaging source integration. |
| `standard-config` | `9a006d3` | 2026-09-02 | Implementation configuration. |

**Bottom line:** Bahmni shows the complete pattern—identity capture, clinical-event-driven sharing, and consent-governed clinician viewing. HealthDoc should finish that pattern in its existing v3 architecture, with the scope, correlation, lifecycle and recovery defects above fixed before claiming M1–M3 readiness.
