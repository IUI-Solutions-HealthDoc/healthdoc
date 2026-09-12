# ABDM live sandbox preflight — 10 September 2026

## Outcome

### Authenticated portal follow-up, 12 September

The owner completed portal login. The application is approved and its profile
lists M1/M2/M3 in the requested scope; sandbox exit review and production
approval are still pending. User dashboard, account navigation and the
Milestone 2/exit form expose no request-ID search or callback-delivery history.
The separate integrator dashboard contains aggregate statistics only. This is
an observed UI limitation, not proof that no diagnostic system exists elsewhere.
No declaration, upload, ticket, completion date or configuration was changed.

A status-only local read at **04:19:20 UTC / 09:49:20 IST** still shows the
same link pending without token/confirmation, a done one-attempt token job,
unconfigured clinician requester metadata and 18 unrelated pending context
notifications. No new token or clinical request was sent. Consent renewal and
the genuine/NHA-approved requester remain required before the next live run.

The initial automatic portal snapshot included the secret the portal displays
in plain text. Later reads were redacted; no secret was copied into reports or
source. The configured secret was not changed. Keep the snapshot private and
plan separate owner-controlled rotation. The
[runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md) now records the inspection;
portal login is no longer an outstanding prerequisite. No milestone case passed.

### Latest follow-up, 12 September at 04:04 UTC / 09:34 IST

**M2/M3 remain unproven live.** Status-only inspection of the existing fresh
operation still shows pending, no encrypted token, no confirmation, and its
one-attempt token job done. No new NHA token request or clinical transfer was
made in this follow-up. The old dispatch did not retain its success HTTP
status; `done` is not retrospective proof of HTTP 202. Same-secret registration
checks in the investigation succeeded; there is no demonstrated secret fault.
Both service-specific lookups returned 200 without a URL override. The general
worker is stopped and all 18 unrelated notification jobs remain untouched.

Local participant consent **expired on 11 September at 23:59 IST**. The
doctor's registration number, identifier type and issuing registry are all
unconfigured. The NHA browser tab remains at the login/CAPTCHA page; the
account owner must log in before any account-specific diagnostics can be
checked. No claim is made that such diagnostics are available in the portal.

Additional implemented repairs:

- Fail closed on HTTP redirects/non-2xx and enforce 202 for token/link,
  HIU consent initiation, data requests and receipt notification. Keep safe
  protocol status/stage diagnostics; do not persist raw responses or tokens.
- Send the receiver's `RECEIVED` session status in HIU delivery receipts,
  with exact entry status and HIP attribution covered by encrypted-receive
  and retry regressions.
- Record an explicit, complete clinician requester in each new consent ask.
  Migration 0069 adds staff identifier metadata and the request snapshot, with
  no invented backfill. Admin UI, doctor readiness state and dispatch guards
  are wired. The migration is applied locally and to the isolated test DB.
  Real Chrome validation rejected an incomplete unsaved profile; no fake
  identity was saved. Full live consent submission is still pending.
- Group multiple selected HI types in one linking operation/POST instead of
  generating a token per type, following the
  [NHA implementation](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/hip/hrp/link/hipInitiated/HIPLinkV3Service.java).
  Each context remains a single document. Existing operation IDs, counters
  and exact retries are preserved; altered selections under the same key are
  refused. No old request was reset and the local credential-use cap is unchanged.

Frontend: **106 tests**, typecheck and touched-file ESLint pass; **214** API
calls match OpenAPI. Final full backend rerun: **1794 passed, six existing
Pydantic warnings, 83.27s**, plus **14 script tests** and migration-chain
integrity (76 migrations, head 0069). The preceding attempt passed 1793 but
had one test-fixture PostgreSQL SSL-upgrade connection error; that file passed
13/13 and the complete rerun passed without changing code or SSL settings.
The underlying intermittent connection cause is not proven. Explicit-file
PR checks had no blockers; the default checker selected no files. Touched
ABDM modules pass Ruff, but the wider users-module check still reports nine
pre-existing findings also present at HEAD; do not claim whole-backend lint clean.
See the [current runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md) for final
verification and the exact user-dependent prerequisites. Historical results
below are not current milestone acceptance evidence.

### Latest follow-up, 11 September at 17:57 UTC / 23:27 IST

**Using the same configured client secret, as requested; not rotated or printed.**
Session plus bridge-services checks returned HTTP **200**. The nested
`bridge.url` matches `https://abdm.healthdoc.world`. Cloudflare lists the
expected active connector, and nginx records the empty public probes reaching
this backend. There is no evidence that changing the secret would fix the
original linking rejection.

**New fixes, independently checked against supplied M2/M3 v2.8 documents:**

- Ten additional callback paths no longer demand the undocumented `X-CM-ID`
  header. A wrong supplied value is rejected. Recipient, request-ID, freshness,
  replay and business guards remain. HIU consent on-init remains CM-required.
  See the [route/header matrix](abdm-callback-header-matrix-2026-09-11.md).
- Auth/outage errors now keep safe status, stage and bounded gateway error
  codes. Raw auth bodies and arbitrary error messages are not retained.
- Normal token-generation failures/crashes stop after one attempt; a failure
  is not permission for five more token requests. Explicit lost-callback
  recovery retains its existing one-extra-attempt limit. Authorization errors
  stop for operator inspection after the client's one refresh. Transient
  non-token transfer failures keep their existing retry behaviour.

**New live operation:** the doctor browser selected only the already approved
synthetic WellnessRecord and queued a fresh link, preserving the expired
original operation. Exact-job dispatch returned without an ABDM client error;
the token job is `done`, one attempt. The diagnostic did not retain its exact
success HTTP status, so `done` must not be substituted for a confirmed callback.

| Identifier | Value |
|---|---|
| Fresh local link | `ffd0eb26-eff8-54f7-b3c4-4dc7d4ecc7b1` |
| Token REQUEST-ID / job | `d613360a-99e5-5fc4-873c-b804d01dba8a` |
| Dispatch completed | 11 September 12:40:42 UTC |
| Last state check | 11 September 17:57:06 UTC |
| Result | **Pending, no token, no link-context job, no callback observed** |

The same participant now has **three recorded token-generation job attempts**
today across both operations. Do not generate a fourth or reset counters. The
NHA document warns of a generation limit; the original request IDs must be
traced before another recovery. A separate deliberately empty linking probe
(no patient data, no link token) returned request-stage HTTP 401 after one
session refresh. This only proves rejection of a credential-incomplete request;
it does not establish the cause of the original real link rejection.

**Verification:** `make test-pg p=tests/integrations k=abdm` → **523 passed,
19 deselected, six existing Pydantic alias warnings, 22.11s**. Separately,
**27 FHIR/settings tests passed**; Ruff and `git diff --check` passed. The
125-test client/header subset is included in the 523, not additional.
Deployed public probes of HIP health-information/request and HIU consent/notify
with their documented routing headers (no X-CM-ID) both returned **422** for
empty payloads, proving the requests reach payload validation after the fix.
They contain no patient data and do not establish authenticated business success.
No HIU consent request or clinical transfer was sent. The 18 context-notify
jobs remain unchanged; the general worker stays stopped. The final browser
shows the normal expired-login screen after the pause, not a completed milestone.

**Tomorrow's execution boundary:** local clinical consent ends at 23:59 IST
tonight. Renew it with the participant before tomorrow's record access. Ask
NHA to trace the missing callback using the [updated support draft](abdm-linking-support-draft-2026-09-11.md)
(not submitted). Once linking is genuinely confirmed, obtain separate PHR
sharing consent, execute scoped transfer and validate the rendered record and
revocation/expiry behaviour. The [next-day runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md)
lists the prerequisites and evidence gates. **M2/M3 are not complete or certified.**

### Follow-up verification, 11 September at approximately 07:30 UTC

- The local stack had stopped during the pause. Restarted its existing
  PostgreSQL, Redis, MongoDB, MinIO, Keycloak, backend, frontend and nginx
  containers, without rebuilds, reseeding, application migrations or starting
  the ABDM worker. The test target checked migrations on the **test** database.
- Final broader gate: **446 ABDM integration tests passed, 19 unrelated tests
  deselected, six Pydantic alias warnings; 22.16 seconds**. Separately,
  **27 FHIR-builder/settings tests passed**. Ruff and `git diff --check` pass.
- Rechecked session plus read-only bridge registration: HTTP **200**. The
  configured HIP is active with `types: [HIP]`; the configured HIU is active
  with `types: [HIU]`. This does not establish linking-endpoint entitlement.
  The response uses `id`/`types`, not `serviceId`/`isHip`/`isHiu`; initial
  diagnostic output with missing flags was not a disabled-service finding.
- The callback URL initially returned 530. Restarted the unchanged
  callback-only tunnel at **07:29:04 UTC**, connector
  `2c0a9f0d-0869-4331-8c1d-cffa8315cbd4`; four QUIC connections registered.
  An empty unauthenticated token callback then returned **400**, proving
  reachability, not business success. This remains a task-session connector,
  not persistent/reboot-tested hosting.
- Live Chrome: signed in as `dev.doctor`, selected the correct existing
  participant, and verified **WellnessRecord expired**, **OPConsultation Not
  linked**, and **no consent requests**. No link/consent submit button was
  pressed and no clinical payload was sent during this follow-up.
- [Prepared NHA investigation draft](abdm-linking-support-draft-2026-09-11.md),
  **not submitted**. It preserves request IDs and identifies missing evidence
  without claiming an unproven cause or attaching participant details.

### Latest, 11 September: token callback works; linking not complete

The participant explicitly approved transmission of the selected demographics
and the single synthetic WellnessRecord's reference/label to NHA. The initial
exact token job was accepted outbound, but NHA's callback received HTTP 400 at
**02:20:37 UTC**. No token was stored on that attempt.

**Fixed a documented contract mismatch:** the supplied M2 v2.8 document
(`M2_Document_16_02_2026_11822aedc7.docx`, §§4.3.2 and 4.3.4) does not list
`X-CM-ID` on the token and link acknowledgement callbacks. HealthDoc required
it. A dedicated dependency for only these two routes now permits its absence,
rejects a wrong value if supplied, and retains HIP recipient, UUID, freshness,
replay and facility/request correlation checks. Other callback dependencies
are unchanged. A routed HTTP regression reproduced 400 before the fix and
passes afterward, including unknown-request and wrong-patient refusal.

Added a **preview-first, single-recovery maintenance command** for an accepted
token request whose callback was lost. It waits a local ten-minute minimum,
requires exactly one completed attempt and no received token/link work,
rechecks identity/documents, refuses other recent token requests for the same
address, audits the requeue and preserves the original REQUEST-ID. A failure
or crashed recovery cannot start another automatic recovery attempt. This is
not a general job reset and not an NHA retry SLA.

```bash
# Inspection only; run inside the configured backend container.
python -m scripts.retry_abdm_token_callback --link-id <link-operation-uuid>
# --apply explicitly requeues eligible work; it does NOT dispatch a worker.
```

**Measured live result:**

| Step | Evidence / final state |
|---|---|
| Corrected public route | Empty synthetic payload with documented routing headers reached payload validation, HTTP 422; it contained no participant/token/correlation data. |
| One recovery | Original token job `294710a4-7011-5add-8b78-a003c58dba3d`, two total attempts, done. |
| NHA token callback | HTTP **202**, token stored encrypted at about **02:38:23 UTC**; no token value recorded here. |
| Exact context-link job | `a27f2e55-78b3-511f-b80b-de1a6491a19e`, three attempts: `AbdmRejected`, session endpoint HTTP **500**, then `AbdmAuthError`. No successful link acknowledgement observed. |
| Token inspection | Unverified diagnostic checks only: three JWT segments, matching HIP/address, no Bearer prefix, issuer expiry not elapsed. These are not signature verification or authority to share. |
| Local expiry | Use window ended **02:43:23 UTC**. Applied the existing expiry branch to this exact link only: status **expired**, encrypted token cleared. No new token was generated. |

The first link rejection's HTTP status/body and the final authentication
failure's exact stage were not retained by the old worker; do **not** invent an
ABDM error code or declare its cause proven. New safe failure summaries now
retain session/request stage, HTTP status and tightly allowlisted ABDM codes,
without arbitrary gateway messages, credentials or patient content.

At that point **64 callback/link/job/contract tests and 18 client tests passed**
in their focused runs; these are engineering checks, not milestone passes.
The first run of the HTTP regression deliberately failed against the old
dependency. Broader final regression results are recorded above.

**Next boundary:** do not repeatedly regenerate tokens or raise the local
credential-use cap to chase this failure. Preserve the request IDs for NHA
investigation, verify the HIP's permission to call the link operation and
gateway stability, then agree a fresh controlled attempt. Rotate the exposed
sandbox client secret noted below. Callback-origin authentication remains a
separate security review: the routing headers are not cryptographic proof,
and this fix does not implement verification of the documented Authorization
token. No HIU consent request or clinical bundle was sent; no M2/M3 workbook
case is marked passed. The general worker remains stopped.

### Earlier, 11 September: actual bundle validates; link queued

The referenced Practitioner table has `name 0..*` and `name.use 0..1`.
The required NameUse binding constrains values when supplied; it does not
require the `use` field. Names and business identifiers remain separate.

After the user's instruction to continue, implemented an **explicitly scoped
development sandbox policy**, not a fake medical registration:

- `ABDM_SANDBOX_LOCAL_AUTHOR_CONTEXT_IDS` defaults to empty. The ignored local
  `.env` enables only the approved synthetic WellnessRecord context.
- The worker also requires development mode, the exact HTTPS NHA sandbox
  gateway, CM `sbx`, a labelled synthetic WellnessRecord, and an active `dev.*`
  author belonging to the document's facility. Other documents/environments
  retain the registration requirement.
- The existing account UUID is represented as `AN` (Account number) under
  `https://healthdoc.world/identifiers/sandbox-staff-account`. The source author
  and name are unchanged; its narrative explicitly says this is not a medical
  registration. No staff credentials or clinical source rows were invented.

The real-source export exposed a second defect absent from the old samples:
the ABHA identifier lacked required `Patient.identifier.type`, and the local
UHID incorrectly used the ABHA namespace. Both are fixed. Local medical-record
IDs now use the HealthDoc patient namespace; ABHA retains the ABDM namespace
and the `MR` type used in the official NRCeS Patient example. Generated synthetic
validation samples now include ABHA so that branch is exercised.

**Actual document validation, not only a generated sample:**

- Read the exact participant/context in a read-only transaction, checking the
  still-active local consent, verified identity, synthetic label, one fabricated
  observation and no diagnoses/orders/prescriptions/consultation notes.
- HL7 validator **6.9.12**, SHA-256
  `0e53ab1d1a6f1e35f505255c0b8ce10a35fcf27e6e96b503640f784cd07e5ad6`,
  with cached **NRCeS ndhm.in#6.5.0 / FHIR 4.0.1**.
- Both actual-document validator runs used a Docker container with **network
  disabled** and `-tx n/a`. The original export failed for missing identifier
  type and consequent reference-profile errors. The rebuilt export passed with
  **zero errors, zero warnings, one informational message**. This is offline
  profile validation, not live terminology or NHA certification.
- Rebuilt document SHA-256:
  `156bf312dda2aa08fea89cdc0ced563b94a2c95cc34e63afbab9ab126d7c3064`.
  Payload and detailed validator artifacts remain only in the private task
  directory `/private/tmp/healthdoc-fhir-validation.A7XfPr`; no patient payload
  is included in this report or committed to Git.
- **120 focused tests passed via `make test-pg`**, including received-record
  identity/consent checks, after the changes. Ruff and diff checks
  pass. The two positive sandbox regressions failed before implementation;
  both patient-identifier regressions failed before their fix.

**Live browser / external state:** doctor Keycloak sign-in succeeded. Selected
the existing verified participant, checked only the labelled WellnessRecord,
and clicked Link selected documents. The browser confirms `pending`; the
OPConsultation remains **Not linked**. Read-back confirms one link operation
`2e36125f-d445-558e-a43a-ec8b03a93c22`, with exact link-token job
`294710a4-7011-5add-8b78-a003c58dba3d`, initially pending with zero attempts.

At that earlier point the outgoing job was **blocked before execution by the approval check** because
it would send patient/ABHA-linked demographics to NHA. Obtain explicit approval
to transmit the selected patient's name, gender, birth year and sandbox ABHA
address to `https://dev.abdm.gov.in/api/hiecm/v3/token/generate-token`, followed
by the single synthetic context's reference/label for linking. Do not retry by
another API or start the general worker to bypass this refusal.

The existing callback-only tunnel had returned HTTP 530. It was restarted at
**02:11:57 UTC, 11 September**, without ingress/registry changes; an empty token
callback subsequently returned HTTP 400. This proves reachability at that time,
not successful callback processing or persistent reboot recovery. The earlier
tool-usage-limit rejection recovered on the later approved attempt.

**Security follow-up:** an early failing test printed the live Settings repr,
including the sandbox client secret. The new tests now use isolated settings;
ABDM client secret, callback secret and OTP relay token are excluded from repr,
with a regression test. Rotate the exposed sandbox client secret and update the
ignored local configuration; do not include the old or new value in evidence.

**Earlier intended sequence (superseded by the live result above):** after explicit transmission approval, recheck callback health and
local consent expiry, dispatch only the exact `link_token` job above, wait for
the token callback, then dispatch its exact `link_context` job before token
expiry. Confirm gateway acknowledgement in the browser before queuing an HIU
request for WellnessRecord only. Participant PHR approval remains a separate,
personal action. No clinical payload or HIU consent request has been sent.
All 18 pending context-notify jobs remain unprocessed; the general
worker is stopped. Remove the single-context local opt-in after this test.

### Earlier: local synthetic document completed; practitioner identifier blocked export

The participant approved renewal through **23:59 IST on 11 September**. The
browser saved a new Clinical Review decision; database read-back confirms expiry
`2026-09-11T18:29:59Z`. The expired earlier decision remains in history. This is
local clinical access only, not ABDM/PHR sharing consent.

The original 10 September token was still waiting and absent from today's
worklist. It was resumed through the normal consultation URL using its existing
token ID, without creating another patient, visit, roster or queue.

Completed through the live browser:

- Saved an encounter whose chief complaint explicitly identifies an **ABDM
  SANDBOX TEST — SYNTHETIC WELLNESS RECORD**, not a clinical consultation.
- Saved explanatory objective/plan notes and **one fabricated pulse value**.
  These are integration-test data, not measurements of the participant.
- Completed the consultation. Read-back confirms one observation, zero
  diagnoses, zero orders, zero prescriptions, and the original token completed.
- Automatic publication produced one OPConsultation context and one
  WellnessRecord context. The OPConsultation is not approved for sharing.
- The Wellness context's generic display was changed by narrowly scoped local
  fixture maintenance, not through a browser feature. The command required the
  exact context/visit/reference, development environment, matching source author,
  synthetic source warning and **no existing patient links**. It changed only
  the display/updated-by metadata and verified one same-transaction audit entry.
  Label: **ABDM SANDBOX TEST — SYNTHETIC WellnessRecord; fabricated observation,
  not clinical advice**.
- The doctor ABDM workspace was opened, the correct UHID selected from two
  similar-name matches, and the labelled WellnessRecord visibly read **Not
  linked**. Neither context checkbox was selected. No link/HIU request was sent.

**Measured blocker:** `_clinical_facts` refuses the exact finalized WellnessRecord
with `Document author has no registration number`. The source author is
`dev.doctor`; its `registration_number` is empty. Do not invent a medical/HPR
identifier, substitute the bridge/client ID, rewrite the author, or remove the
production export guard. Either an appropriate approved practitioner identifier
must be supplied, or a separate explicit sandbox identity policy must be agreed.
The complete live bundle has therefore **not** been built/validated; the prior
export-label regressions are not a substitute for that read-back.

**Standards clarification after rechecking official documentation:**
[NRCeS Practitioner 6.5.0](https://nrces.in/ndhm/fhir/r4/StructureDefinition-Practitioner.html)
requires one or more identifiers with type and value. It does **not** fix the
identifier to a medical-registration/HPR number. Its
[identifier value set](https://nrces.in/ndhm/fhir/r4/ValueSet-ndhm-identifier-type-code.html)
includes non-medical identifier types such as employee and account numbers.
HealthDoc's present mapper is narrower: it always emits `MD` under the doctor
registry namespace and therefore must not populate that field with a local UUID.
The current test account has neither a registration number nor an employee number.
Its existing staff UUID could only be used under a deliberately implemented,
correctly typed local-account namespace, not relabelled as a licence. A proposed
sandbox-only mapping for this approved synthetic document needs explicit approval,
must leave production checks unchanged, and still needs actual profile validation
and sandbox interoperability evidence. No such mapping has been enabled.

The callback probe returned HTTP 400 (expected rejection of an empty request),
confirming reachability at this check. There are now **18 pending context_notify
jobs**: the 16 older jobs plus this encounter's two new contexts. No job was
dispatched and no clinical payload was sent. The general worker remains stopped.

Next: configure the approved practitioner identifier, recheck exact-document
export/FHIR validation and label, then link only the WellnessRecord and request
only that type/date window through HIU. The participant must approve in SBX.
This preparation does not complete any M2/M3 external acceptance case.

### 11 September follow-up: consent-page defect fixed; renewal required

The participant explicitly approved local patient-level Clinical Review access
until 23:59 IST on 10 September. The browser recorded that decision at 22:07 IST,
using the written channel to record the participant's chat approval, not a claim
that a separate signed form or OTP ceremony occurred. The screen confirmed
**Consent recorded**, with expiry on 10 September.

The next browser read was interrupted by the tool's usage-limit rejection. On
resumption after midnight, the login session had expired and the recorded consent
was past its approved expiry. No renewal was submitted and no emergency access
was used. No synthetic observations, finalized test document, linking request or
HIU consent request has been created by this execution. Today's worklist is empty;
the previous day's visit must be located and checked rather than duplicated.

The post-save permission error was a separate frontend defect: selecting the
saved consent automatically requested `/audit/data-access`, which correctly allows
only auditor/admin. `ConsentAccessHistory` now mounts the ledger request only for
those roles, isolates it by signed-in user/role/consent, and displays permitted-role
request errors with retry instead of an empty table. Doctor/receptionist/nurse
consent workflows no longer request the restricted ledger. Backend permissions
are unchanged.

Fresh evidence on this working tree:

- All **100 frontend tests passed**, including 16 new role/rendering regressions.
- TypeScript and targeted ESLint passed.
- Live Keycloak doctor sign-in succeeded. The existing consent detail loaded and
  displayed the role-specific history notice, with no permission-error banner.
- A complete, pre-filtered ten-minute nginx log window showed four successful
  consent-record GETs and zero `/audit/data-access` requests. An earlier truncated
  log read was discarded and was not treated as evidence.

**Next human decision:** approve a new explicit local consent expiry if the test
should continue today. SBX sharing consent is still separate and must be approved
by the participant in the SBX app. Public callback availability must be rechecked
before sending anything; yesterday's connector evidence is not current proof.

### Live M1 follow-up: OTP verification and patient binding succeeded

Branch: `fix/abdm-otp-live-verification`, based on UI commit `658e791`.
The participant confirmed they have both sandbox identifiers, selected their
own local record, and entered the existing ABHA. No identifier or OTP is retained
in this report.

The first request failed with upstream HTTP 400, exposed locally as HTTP 502.
Allowlisted diagnostics identified `loginId` (request
`15a1974e-8dbc-4573-b8df-db413c021e22`). The public route normalises the number to
digits, but the OTP service encrypted that stored representation without
restoring the 2-4-4-4 hyphenated representation already used by the lookup API.
The shared formatter now runs before RSA encryption. The corrected browser
request returned HTTP 200 and displayed the gateway's OTP-sent confirmation.
The participant entered and submitted the OTP themselves. Verification returned
HTTP 200 and the browser displayed **ABHA verified and linked**.

Read-only database confirmation: selected patient `identity_status=verified`,
number and sandbox address saved, encrypted credential and key version present,
link timestamp present, exactly one active matching identity in the facility.
No credential was decrypted or printed. The UI development reload reset the
form once; the existing record was reselected rather than registered again.

Additional fixes: user-facing `abdm_rejected` now distinguishes refusal from a
temporary outage without displaying the raw gateway body. Diagnostics retain
only request UUID, HTTP status, allowlisted field names and constrained ABDM
error codes. Regression tests decrypt synthetic payloads to check the exact
outgoing representation and assert that private error values never enter logs.

Fresh verification on this working tree:

- 74 focused identity/lookup/binding/session tests passed.
- 397 ABDM integration tests passed, 19 deselected, four existing alias warnings.
- 84 frontend tests passed; TypeScript and changed-file Ruff checks passed.
- 214 frontend API calls match OpenAPI; no contract document overwritten.

**This is one successful M1 happy path, not completion of M1.** Workbook row 72
also asks for full profile retrieval/display, field edit restrictions, incorrect
OTP behaviour and resend handling. Those have not all been proven live. Row 98
has positive binding evidence, but duplicate-binding refusal and the new-ABHA
branch still need case-specific live evidence.

At 19:59 IST the public callback again returned HTTP 530. A temporary connector
using the unchanged callback-only configuration was started at 14:29 UTC;
all 16 empty callback probes then reached HealthDoc and were rejected as expected.
The persistent service remains unrepaired; this is not reboot-safe evidence.

### 10 September preparation (superseded by the follow-up above)

The participant explicitly approved creating one clearly labelled synthetic
WellnessRecord and exchanging it between HealthDoc's HIP/HIU through NHA's
sandbox. That approval does not stand in for the separate PHR consent action.

Browser preparation on 10 September:

- HOD added today's General Medicine roster for the development doctor.
- Reception opened a queue labelled as an ABDM synthetic-record test clinic.
- Reception selected the already verified participant record and created one
  OPD visit/token. No duplicate patient was registered.
- Doctor worklist displayed that token, but consultation remained **Record
  locked** because there was no local Clinical Review consent.
- The normal `/consent` form was opened for the selected participant. Its
  defaults were **Written form**, **Patient**, and an empty expiry. Nothing was
  submitted at that first pause. The subsequent explicit approval and saved
  time-limited consent are recorded above. Emergency/break-glass was not used.

No encounter, vitals, finalized test document, link request or HIU consent request
has been created at this pause. The earlier zero-context/zero-link baseline
therefore has no new test document from this execution. All 16 earlier queued
notifications were left untouched; the general worker remains stopped. Dispatch
only explicitly verified test-job IDs with `run_once(ident=...)` when appropriate.

The Clinical Review form records patient-level consent at this facility; it does
not offer a visit-only scope. Obtain explicit participant approval with a short
expiry before recording that local access decision. Do not represent the form's
default channel as evidence of a signed form or completed OTP ceremony. The later
SBX app sharing decision remains the participant's own action.

**Export defect repaired before creating observations:** the Wellness mapper
correctly excludes the consultation's notes, but the exporter also discarded
the registered context's display label. A warning placed only in the chief
complaint would not accompany the Wellness document. `_clinical_facts` now passes
the exact context label into `build_clinical_bundle`, which preserves it in
`Composition.title` and escaped narrative, leaving the canonical
`Composition.type` unchanged. Unlabelled documents retain their standard titles.
This follows the separate label/type fields in
[FHIR Composition](https://www.hl7.org/fhir/R4/composition-definitions.html#Composition.title)
and the [NRCeS WellnessRecord profile](https://nrces.in/ndhm/fhir/r4/StructureDefinition-WellnessRecord.html).

Nine new regression cases failed before the fix; **65 focused builder, export,
publisher, durable-job and transfer-scope tests pass** after it. Ruff checks and
formatting pass. These are local regressions, not a new full NRCeS validator run
or proof of received external data. Before transmitting the eventual fixture,
verify its registered display actually contains the synthetic warning and check
the resulting bundle; automatic publication still supplies a generic label.

At approximately 22:00 IST, the local health route returned HTTP 200 and an empty
public token callback returned HTTP 400, confirming reachability rather than
successful callback authentication or processing. A task-session connector was
restarted at 16:23 UTC using the unchanged callback-only configuration; persistent
tunnel service repair remains outstanding.

### Earlier baseline (superseded where the live follow-up differs)

### Follow-up at 16:50 IST

**Browser access recovered.** A real Keycloak sign-in as `dev.receptionist`
completed and landed at `/receptionist/registration`. The first submission used
an expired login form; Keycloak restarted the login, and the fresh submission
succeeded. The live page displays the receptionist-only registration, patient
search, queue and consent navigation. The participant handoff is now selection
or registration of their own matching local test record, without disclosing
identifiers or OTPs in chat.

**The temporary tunnel did not persist.** A fresh callback probe returned HTTP
530 after the earlier task-session connector ended. The installed launch daemon
`/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` has only
`/opt/homebrew/bin/cloudflared` in its arguments; it does not specify `tunnel run`
or the HealthDoc configuration. Its system configuration at
`/usr/local/etc/cloudflared/config.yml` contains only a log-directory setting.
By contrast, the user's callback-only configuration passes
`cloudflared tunnel --config ... ingress validate`. Approval has been requested
to repair the existing service without changing credentials, DNS or ingress
scope. **Do not rely on the earlier successful probes as current availability.**

The checkout is now `feat/ui-modernization-and-audit-pagination`, commit
`658e791d1a2d8552cbc76dd2400b62fea15003f8`, changed outside this execution.
The ABDM backend, receptionist identity panel and doctor ABDM workspace have no
diff from the earlier baseline. Earlier automated-test counts below belong to
the earlier baseline, not a fresh full regression claim for this UI branch.

**Preflight partially passed; M1, M2 and M3 live acceptance remains incomplete.**
The broken public callback tunnel was restored. No participant OTP was requested,
no identity was entered, no patient consent was granted, and no clinical record
was sent by this execution. Do not represent these checks as NHA certification.

At this earlier baseline, the user had reported PHR registration but had not
yet confirmed both identifiers. Both are now confirmed and the live verification
above supersedes that earlier uncertainty; neither belongs in this report.

Application baseline: `main`, commit `23c89e0` (PR #551 promotion merge).
The checkout switched from `fix/external-result-input` to `main` externally during
the checks. No branch switch, application-code edit, commit, push or PR was made
by this execution. The supplied `ABDM DOCS/` files were left unchanged.

## Fresh evidence

| Check | Observed result | Interpretation |
|---|---|---|
| Local `GET /api/v1/health` | HTTP 200, `healthdoc-api`, environment `dev` | Local backend responds. |
| Application migration | `0068` | Read-only observation; no application migration performed. |
| Gateway credentials and bridge-services read | HTTP 200, request `94bc693f-5721-41d4-b5d1-67da821b262a` | Credentials work. Earlier session attempts were intermittently unavailable, including HTTP 504. |
| Registered bridge URL | `https://abdm.healthdoc.world`, matches runtime | No registration change needed or performed. |
| Registered services | `SBXID_053401_HIP`, `SBXID_053401_HIU`, both active | Registry read-back; not proof of complete HSP/HFR onboarding or successful exchange. |
| Local facility mapping | One facility matches configured HIP service ID | Mapping exists locally; no rows edited. |
| ABHA public certificate | HTTP 200; current 4096-bit RSA key matches runtime | Encryption-key rotation is not the present blocker. Request `61760183-510b-48f9-97cb-66d090f9b58e`. |
| Public callbacks before recovery | All 16 probes returned HTTP 530; response body identified Cloudflare 1033 | Named tunnel had no active connection. |
| Public callbacks after recovery | All 16 empty POST probes rejected as expected; doctor script exit 0 | Routes are reachable. Empty-probe rejection does not prove successful authenticated callback processing. |
| Public non-callback route | `GET /api/v1/health` returns HTTP 404 after recovery | Expected callback-only ingress restriction, not an unhealthy backend. |
| Delivery queue | 16 `context_notify` jobs, all pending | Worker left stopped; existing jobs were not dispatched. |
| Link-OTP relay settings | URL and bearer token both absent | Patient-initiated discovery/linking cannot deliver its OTP yet. |
| Backend focused regressions | 393 passed, 19 deselected, 4 Pydantic alias warnings; 53.22 seconds | Separate test database; mocked NHA traffic is not live milestone evidence. |
| Frontend unit regressions | 83 passed, zero failed/skipped | Not browser acceptance. |
| Frontend TypeScript | Exit 0 | Static check only. |
| Frontend/backend route contracts | 214 API calls match OpenAPI; exit 0 | Route existence, not clinical/wire interoperability. |
| Browser acceptance | Initial HealthDoc login page readable; subsequent tab reads/new tab creation returned `User unavailable` even after user replied ready | No completed M1/M2/M3 browser journey. Native Chrome fallback did not provide usable page content. |

Commands executed:

```bash
make test-pg p='tests/integrations' k=abdm
cd frontend
npm test
npm run typecheck
# From backend/; no --write, so the contract document was not overwritten:
../.venv/bin/python -m scripts.check_frontend_contracts
# From repository root:
bash scripts/abdm_sandbox.sh doctor https://abdm.healthdoc.world
```

## Tunnel recovery and operational boundary

The existing process had no active tunnel connections. A connector was started
using the unchanged local configuration:

```bash
cloudflared tunnel --config /Users/ritikkumar/.cloudflared/config.yml \
  run 5f5ceb29-86e7-43cd-8c06-e41e75b1133b
```

Four QUIC connections registered at Delhi edges at 08:13:35–08:13:38 UTC
(13:43:35–13:43:38 IST). Connector ID:
`c0a1fdcd-ff4e-448e-bd4d-88a6cbaf65ae`.

Only the existing `/api/v3/*` callback paths are forwarded to nginx. Other
public paths still return 404. No firewall, credentials, DNS, bridge URL, service
registration or ingress rule was edited. This is a running task-session
connector, **not a newly installed persistent/reboot-tested service**. Keep the
origin awake and verify reachability before testing; arrange a supervised
connector before relying on unattended callbacks.

Cloudflare's [1033 troubleshooting guidance](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/)
distinguishes absence of a connected tunnel from an application routing error.

## What the supplied documents change

The folder contains 20 files, not a single consistent-version checklist.
Relevant evidence reviewed includes the M1 v1.2 workbook, M2/M3 workbooks,
November 2025 FAQ, relevant sections of the 300-page M1 API PDF, and the
February 2026 M2/M3 specification sections. The healthcare-professional API
documents concern a separate registry surface. The PHR/mobile/locker workbook
is not automatically an HMIS obligation merely because HealthDoc uses a PHR
app as its test counterpart. Older API-list workbooks contain v1/v0.5 routes;
do not overwrite current v3 paths from those older lists.

### A. HMIS HI-type scope is wider than the implemented five

Source: `ABDM DOCS/FAQ_20_11_2025_808a25df64.pdf`, **page 2, question 2**.
It states eight HI types for HMIS. Current `hip/gateway.py`, FHIR builder and
frontend `features/doctor/abdm/api.ts` support only:

- OPConsultation
- Prescription
- DiagnosticReport
- DischargeSummary
- WellnessRecord

**Not implemented end-to-end: Invoice, ImmunizationRecord,
HealthDocumentRecord.** These must not be enabled by merely widening an enum.
Each needs an approved source workflow, finalization/version policy, exact
document context, FHIR mapping and validation, publication/linking support,
consented transfer, and HIU rendering/access controls with regressions.

The older M3 workbook mentions seven types and an “any one” test branch. That
does not override the FAQ's explicit HMIS requirement. Confirm HealthDoc's
registered category and current acceptance scope with NHA; do not claim all
milestones complete after showing a single supported type.

### B. M1 gaps now have explicit case references

Source: `Copy_of_M1_ABHA_CREATION_AND_VERIFICATION_WITH_APIS_UPDATED_V1_2_7_Aug_1_58de4446bc.xlsx`,
sheet `ABHA CREATION AND VERIFICATION`.

| Case / source row | Gap and required work |
|---|---|
| `CRT_ABHA_102`, row 23 | Actual displayed enrolment consent and recorded affirmative acceptance. A hardcoded consent code/version in an outbound payload is not evidence the participant consented. Do not run new-Aadhaar enrolment through the current UI as a compliant flow. |
| `CRT_ABHA_106`, row 27; verification resend cases | Controlled resend UI and server-enforced timing/count limits specified by the checklist. “Start again” is not equivalent to a tested resend flow. |
| `CRT_ABHA_109`, row 30 | Separate alternate communication-mobile verification continuation. The current optional mobile input does not implement it. |
| `CRT_ABHA_112`, row 31 | Address suggestions/custom selection, validation and availability handling. |
| `CRT_ABHA_114`, row 33 | API-derived ABHA card view/download with correct token and profile context for the applicable private-integrator flow. |
| `VRFY_ABHA_101/102/201/202`, rows 69–73 | Current UI exposes ABHA-number + mobile OTP only; required alternate identifier/authentication combinations remain unimplemented. |
| `VRFY_ABHA _301–305`, rows 75–79 | Find ABHA by mobile and explicit account selection; handle multiple results without guessing. |
| `VRFY_ABHA_401–405`, rows 81–85 | Existing-ABHA retrieval via Aadhaar and associated error/resend cases. |
| `SHARE _PATIENT_PROFILE_701`, row 100 | Real Scan-and-Share registration ticket and expiry/read-back workflow, not only a callback acknowledgement. |

Account-token purpose, expiry and continuation storage also remain engineering
work. The M1 account token must not be treated as proof that an M2 link token
has been generated. Current M2 linking has its own callback-driven operation;
verify that separately in the live run.

### C. M2 and M3 need full external evidence

- M2: finalize a permitted document, obtain/receive the linking token, confirm
  the context link, pull and display the same record in the PHR, and exercise
  grant/revoke/expiry as applicable. Test patient-initiated linking after the
  HIP-owned OTP relay is configured. FAQ question 35 explicitly assigns that
  OTP delivery to the HIP.
- M3: request the correct record types/date interval, see the request in the
  PHR, approve/deny there, receive an external HIP's encrypted payload, verify
  patient binding and display, then prove revocation and expiry block access.
- Verify HSP facility registration/software linkage and appropriate practitioner
  data. Active mock gateway services are not, by themselves, evidence of that.
- Review callback-origin controls, unresolved reply/timeout recovery and actual
  clinical documents against the current NRCeS validation requirements.
- The supplied FAQ warns that repeated generate-token calls can block the same
  facility/address and that linked care contexts cannot simply be unlinked.
  Use a deliberate test manifest; do not repeatedly generate tokens or link
  arbitrary seeded records to a participant's real sandbox identity.

## Remaining live sequence — after the current linking failure is resolved

1. Review NHA's failure against the exact context-link request ID above and
   verify service permission, credential rotation and gateway health. Do not
   reset attempts, extend the expired token's use window or keep generating
   tokens. The local consent renewal and synthetic encounter are already saved; do not
   repeat registration, M1 OTP, consent creation, observations or finalization.
   Local access expires at 23:59 IST on 11 September and is patient-level.
2. Re-run the exact Wellness export and verify its label, content and FHIR profile
   before linking. Do not share the automatically published OPConsultation
   context or unrelated seeded records.
3. Recheck public callback availability, then link only the verified Wellness
   context. Track its exact request/callback/job IDs without starting the general
   queue consumer or repeatedly generating link tokens.
4. Request only WellnessRecord with a narrow date interval/expiry from HealthDoc's
   HIU. The participant approves or refuses in their own SBX app.
5. Verify encrypted transfer, receipt and display, then the applicable refusal,
   revocation and expiry cases. Keep secrets and identifying clinical screenshots
   out of the repository. One successful round trip is not all three milestones.

The [case-by-case ledger](abdm-milestone-case-ledger-2026-09-10.md) contains
66 M1, 36 M2 and 16 M3 source rows. Two M1 rows have PARTIAL evidence; no M2/M3
case is marked passed by this local preparation. These counts are not
mandatory-case counts and exclude API-only appendix entries without IDs.
