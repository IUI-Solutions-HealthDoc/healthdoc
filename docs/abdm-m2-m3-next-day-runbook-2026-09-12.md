# M2/M3: next-day execution gates — 12 September 2026

## PR handoff — 13 September 2026, 14:08 IST

This section supersedes the older inline-reply work item below. It is **local
engineering verification, not M1/M2/M3 certification or a live M2/M3 exchange**.

### Completed in `fix/abdm-live-operations`

- Discovery, link-init, negative confirmation and Scan-and-Share replies now
  commit durable acknowledgement intent before network delivery. Retries keep
  their outbound request ID and frozen payload. Bounded reply snapshots are
  encrypted with reply/facility/kind associated data; cleanup erases them after
  delivery or expiry. Replaying a callback cannot restore erased bytes or
  extend the deadline.
- Link-init uses a PostgreSQL transaction lock, including the concurrent
  first-insert case. SMS delivery occurs only after commit. A Redis guard
  prevents duplicate delivery attempts under the original link deadline;
  uncertain delivery needs a new patient action. Wrong-OTP callback replays
  cannot spend attempts twice after a database rollback. Patient, mobile and
  exact finalized-document bindings are rechecked before dispatch.
- Successful mediated confirmation retains the previously added durable,
  scope-checked acknowledgement. None of these M2 acknowledgement jobs starts
  clinical transfer. The owner has deferred SMS provider setup; no SMS provider
  was configured and no message was sent.
- Scan-and-Share refuses an invalid/missing legacy UHID with a reconciliation
  error instead of crashing or inventing a numeric token. This does **not**
  implement the separate real reception-queue ticket workflow.
- The broader verification exposed billing number truncation: permitted
  20-character facility codes do not fit the old 30-character invoice, receipt
  and refund columns. Migration 0072 widens all three to 50 without rewriting
  identifiers; downgrade refuses to discard long numbers. Tests cover each
  allocator, real payment/refund flows, and migration rollback guards.
- Billing test facility IDs no longer use only five UUID characters. Committed
  synthetic audit evidence in the concurrency test is retained with its parent
  facility; no append-only trigger is disabled to tidy test data.
- Earlier accumulated work remains included: preview-first development identity
  repair, safer provisioning errors, removal of unverified login certification
  claims, read-only operational diagnostics, tunnel supervision renderer/tests,
  and sanitized support/runbook evidence. The support ticket is prepared, not
  submitted.

### Final verification

| Gate | Result |
|---|---|
| Full `make test-pg` | **1,904 passed**, six existing Pydantic alias warnings |
| Repository script tests | **20 passed**; also added to GitHub CI collection |
| Frontend unit tests | **112 passed** |
| Frontend TypeScript and ESLint | Passed |
| Frontend/backend route contracts | **214 calls** match OpenAPI |
| Schema/spec checks | Zero blockers; schema drift zero warnings |
| Migration chain | **79 revisions**, linear, head **0072** |
| Explicit changed-backend convention check | Zero blockers; generic callback idempotency warnings remain (ABDM uses correlated REQUEST-ID, not the staff API header) |
| Production frontend build | **Not verified**: failed fetching IBM Plex Sans/Mono from Google Fonts in this network-restricted environment |
| GitHub CI | Not yet run for the new commit at the time of this entry |

The full gate was not green on the first attempt. Failures exposed the omitted
identifier in the new concurrency fixture, its immutable-audit cleanup boundary,
the pre-existing short facility-code collision, and the real billing-width bug.
One run also encountered a PostgreSQL SSL-upgrade connection error; that test
passed unchanged on targeted and final full reruns. No test was skipped or
weakened to make the final gate pass. `make test-pg` ran its convention checker
before commit, when it sees no committed changed files; the explicit file-list
check was run separately rather than treating that empty check as coverage.

### Local deployment and remaining live gates

Both local application and isolated test PostgreSQL are at **0072**. Revision
0070 was already applied before the further recovery work; 0071 and 0072 are
incremental follow-ups, not rewrites of an applied migration. Before applying
0071–0072, this ignored backup was created and passed `pg_restore --list`:

`backups/abdm-0071-20260913/healthdoc_healthdoc_20260913T083253Z.dump`

Directory mode 0700, dump mode 0600. Archive readability is **not** a populated
restore rehearsal or production disaster-recovery proof. Only the cleanup
service was restarted; the general outbound worker remains stopped.

At **08:38:04 UTC / 14:08:04 IST**, read-only post-upgrade metadata still showed:
the selected token job at two attempts, no HIP linking token/confirmation,
18 pending context-notify jobs, one older pending link-context job, two done
token jobs, and zero received-content rows or transfer keys. Local consent was
active, but authorized M3 requester metadata remains incomplete. No third token
generation, consent request, clinical transfer or unrelated queue drain occurred.
The final HTTPS health/SSO recheck was blocked by an approval-service usage-limit
error; earlier successful checks below are historical, not a fresh health claim.

The next live steps remain: NHA trace/redelivery for the existing missing token
callback, authorized or NHA-approved M3 requester details, participant PHR
approval, then a scoped synthetic encrypted transfer and read-back. SMS-dependent
alternative linking is deferred by the owner. Preserve those gates in PR review;
do not infer milestone completion from passing local tests or outbound HTTP 202.

## Local M2 safety and recovery fixes — 13 September, 09:36 IST

**Progress without an NHA reply; not a completed M2/M3 sandbox exchange.**
The owner confirmed that no SMS provider/OTP relay exists yet and wants that
setup deferred. No relay credentials were invented and no SMS was sent.

### Fresh live evidence

- At **03:46:42 UTC / 09:16:42 IST**, and again after the migration at
  **04:05:48 UTC / 09:35:48 IST**, the selected HIP operation remained pending:
  no link token, no confirmation, same two-attempt token job. Local Clinical
  Review consent is active; requester registration remains incomplete.
- All 16 public callback routes passed empty unauthenticated reachability
  checks. The retained nginx log window since the previous check contained
  one token-callback POST returning 400, consistent with our empty probe;
  no new genuine callback was observed. Reachability still does not establish
  connectivity from NHA or acceptance of a genuine callback.
- Real Chrome/Keycloak doctor sign-in, doctor queue, exact authorized patient
  selection, ABDM workspace and both status refresh actions worked. The
  synthetic WellnessRecord remains `expired, pending`; M3 fields/submission
  remain disabled for missing requester metadata. The other document was not
  selected. No OTP request, consent submission or clinical transfer occurred.
- Post-migration health and silent-SSO returned 200 with certificate
  verification. Nine services remain running, with four datastore health
  checks green. The general outbound worker remains stopped; the cleanup-only
  service is running. Counts of unrelated jobs and received/key rows did not
  change: 18 context-notify pending, one older link-context pending, two token
  jobs done, zero received content/transfer keys/HIP tokens.

### Implemented and verified locally

1. **Facility/patient scope:** mediated confirmation is locked and scoped to
   the configured facility; deleted, merged, changed-address and mismatched
   patient bindings are refused before OTP proof is spent.
2. **Exact documents:** confirmation refuses a missing, unavailable, duplicate
   or partial document selection instead of confirming whatever remains.
   Link-init transaction replays cannot change the patient/document selection
   or restart a closed/expired operation.
3. **Acknowledgement durability:** a successful mediated confirmation commits
   its state and acknowledgement job together. Gateway failure cannot roll
   back the confirmation after consuming the proof. Retry uses the same
   outbound request ID, rechecks current patient/document scope, and never
   starts a clinical transfer.
4. **Database-failure boundary:** Redis reserves successful proof for the
   exact original confirmation request ID under its original TTL. Only that
   same proof can retry a rolled-back database transaction; attempts/expiry
   are not reset. Committed replays are checked using a keyed fingerprint,
   not plaintext OTPs or an offline-guessable bare OTP hash.

The first safety run produced **11 failures and one pass against the original
handler**; the scope fixes then passed all 12. The final broader gate passed
**714 integration/FHIR/schema tests**, including real PostgreSQL concurrency
and migration round-trip/guard checks and the actual Redis Lua script on a
unique synthetic key in logical test DB 15. Six existing Pydantic alias
warnings remain. **112 frontend tests passed**; changed-file Ruff, migration
chain validation and `git diff --check` passed. This is not a new full-backend
or GitHub CI result.

The first broad run failed because the host's `/usr/bin/java` is a macOS stub
with no configured runtime (28 failures / 80 setup errors). The existing
Temurin 21 JDK under `/private/tmp/healthdoc-crypto.TE4Ekt/` was verified and
selected explicitly with `HEALTHDOC_JAVA`; the helper was rebuilt with
`HEALTHDOC_JAVAC` and the pinned Bouncy Castle checksum. The same suite then
passed without weakening tests. This is a temporary host runtime location,
not a durable installation; see `backend/crypto/README.md` for setup.

### Local deployment

Migration **0069 → 0070** is applied to both test and local application
PostgreSQL. It only extends the callback-reply kind CHECK constraint; it does
not rewrite patient rows or start workers. Before application upgrade, a
restricted-permission, ignored backup was created:

`backups/abdm-0070-20260913/healthdoc_healthdoc_20260913T040510Z.dump`

Directory mode 0700, dump mode 0600. `pg_restore --list` passed. This checks
archive readability, **not a full restore rehearsal or production recovery**.
The migration's downgrade is tested on a connection-local PostgreSQL shadow
table and refuses to discard committed M2 confirmation evidence.

### Still required

- Missing HIP-token callback: trace/redelivery via NHA using the existing
  request ID; no third generation was attempted. The local fixes above do
  **not** explain or solve that missing delivery.
- M3: authorized clinician requester details, or NHA-approved sandbox identity
  policy, followed by participant PHR consent and scoped encrypted read-back.
- Alternative patient-initiated M2: SMS setup is deferred. Discovery/init and
  negative-confirmation replies still have inline network work; initialization
  resend/crash behavior must be exercised before enabling that alternative.
  Successful confirmation now has durable recovery, but that does not make
  the whole alternative workflow live-proven.
- When authorized to exercise it, dispatch only the specific acknowledgement
  job. Do not start the general worker against unrelated queued work.
- Changes remain uncommitted; no PR, ticket submission or certification
  declaration was made in this session.

## Live retest and fresh M1 verification — 13 September, 05:02 IST

**Approved live tool access is working again.** The earlier usage-limit stop
is historical. These are fresh live observations, not a replay of test-suite
results or a claim of complete M1/M2/M3 certification.

| Check | Observed result |
|---|---|
| Docker services | All nine services running; PostgreSQL, MongoDB, Redis and MinIO report healthy. |
| Local health | `https://localhost/api/v1/health` returned **200**, using the configured development certificate without `-k`. |
| Silent SSO | `/silent-check-sso.html` returned **200** with certificate verification. |
| Public callbacks | All **16** configured callback routes were reachable and rejected empty unauthenticated probes as expected; no empty callback was accepted. |
| Gateway/registration | Existing credentials obtained session access; bridge-services returned **200**, callback URL matched, HIP and HIU were active. |
| Cleanup | Cleanup-only worker's last three entries reported completion with zero items cleared. The general worker remained stopped. |
| Doctor browser/API | Fresh Keycloak login, queue page and selected-patient ABDM workspace worked. Queue and critical-alert stream each returned **200**. |
| Local consent | Renewed Clinical Review consent remained active through **14 September, 23:59:59 IST**, with the correct patient match. |
| M2 status | Approved synthetic WellnessRecord still showed historical **expired** and separate **pending** operations. No link token or confirmation. |
| M3 status | Incomplete-requester warning visible; request fields/button disabled. No consent request or received content. |
| Alternate mediated linking | OTP delivery URL/authentication still absent. No alternate OTP delivery was attempted. |

### Fresh M1 existing-ABHA flow

The participant explicitly approved **one** fresh M1 login-verification OTP
request. Logged in through Keycloak as the existing development receptionist,
searched the supplied ABHA, selected the single exact existing patient match,
and used **Use existing ABHA**. No new patient, ABHA or visit was created.

- `POST /api/v1/abdm/abha/login/request-otp` returned **200** at
  **12 September 23:27:57 UTC / 13 September 04:57:57 IST**.
- A verification submission then reached the server. No OTP was requested in
  chat, read from storage, copied to this document or entered by the agent.
- The browser navigated/reloaded the registration page while that response was
  returning. Nginx logged **499** on the verification request at **23:28:30 UTC**.
  The cause of that navigation is not established; it must not be reported as
  a proven application defect or gateway rejection.
- Read-back proves the backend nevertheless committed identity verification at
  **23:28:30.756524 UTC / 04:58:30 IST**, and consumed the selected participant's
  OTP session. The number and address match the participant-provided values,
  the record remains active, and its address still matches the pending HIP
  operation. Only booleans/timestamps were retained in diagnostic output.
- The receiver only reaches that identity commit after validating successful
  OTP authentication, one active returned account and a linking credential.
  Thus this is fresh server-side evidence of the existing-ABHA M1 flow, but
  **not a captured final browser success banner**: the navigation lost that
  transient screen. No second OTP request was sent.

The final metadata check at **23:31:44 UTC / 05:01:44 IST** still showed the
same two-attempt HIP token job, no HIP token, no confirmed link, no received
content or transfer keys, and unchanged unrelated queued jobs. The successful
M1 login credential was **not** substituted for the distinct missing M2 HIP
link token. M2/M3 remain blocked by callback delivery and requester setup;
PHR consent and scoped encrypted exchange remain unperformed.

Remaining action requiring external input: trace the observed NHA 202 with its
REQUEST-ID, and obtain an authorized requester identity or NHA-confirmed test
policy. The separate SMS relay is only an alternative M2 route, not a fix for
the missing HIP callback. The support draft is updated but remains unsent.

## Consent renewed and browser verified — 13 September, 00:10 IST

**The participant has now submitted the renewal.** This supersedes every
earlier instruction below saying the consent form still awaits submission.

- Metadata checked at **12 September 18:37:46 UTC** confirms the latest
  Clinical Review decision was granted at **18:32:12 UTC / 13 September
  00:02:12 IST** and expires **14 September 18:29:59 UTC / 23:59:59 IST**.
  It is active and belongs to the selected participant. No agent-created
  consent grant or expiry extension was performed.
- Chrome visibly showed **Consent recorded**. The doctor then opened
  `/doctor/abdm`, searched by the participant's supplied identity and selected
  the previously verified UHID. Name/DOB search returned two records; the
  other same-name record was not selected, merged or changed.
- The selected ABDM workspace loaded and displayed a verified ABHA binding.
  The approved synthetic WellnessRecord showed **expired, pending**, matching
  its historical expired operation and separate pending operation. Its link
  checkbox is disabled. A separate OPConsultation was listed but was not
  selected or authorized for transmission.
- M3 requester fields and the consent-request button remain disabled with an
  explicit incomplete-profile message. No consent request, clinical transfer,
  new token generation or unrelated notification was sent in this follow-up.
- The **18:37:46 UTC** snapshot still showed the selected token job done with
  two attempts, no stored token or confirmation, no received content or transfer
  keys, and the same unrelated pending jobs. The last directly observed NHA
  response remains **202 at 18:25:41 UTC**; no later outcome is inferred.
- Checked the alternate patient-initiated linking prerequisites using booleans
  only: **OTP relay URL absent, relay authentication absent**. The mediated
  flow cannot deliver a code in this deployment yet. This is a separate path
  from HIP token generation, not an explanation for the missing NHA callback.

**Current tool boundary:** at **18:40:21 UTC / 00:10:21 IST**, the approval
service refused another read-only Docker log check because its usage limit was
reached. Its subsequent status query did not run. Do not describe those checks
as passing or use another execution route to bypass that refusal. Local
documentation updates can continue; live verification needs approved tool
access to resume. The browser was left at the participant's ABDM workspace.

### What can unblock the remaining live steps

1. **HIP-initiated M2:** obtain the missing callback or trace its delivery using
   the existing REQUEST-ID in the support draft. With approved tool access,
   inspect for late delivery before deciding any next action. Do not generate
   a third token, resurrect the old operation, or extend token validity.
2. **Patient-initiated M2 alternative:** the owner must supply an authorized
   OTP delivery service/relay and its credentials privately in deployment
   configuration. The existing contract sends recipient, message, purpose
   and expiry to that relay. Confirm the provider, permitted recipient and
   delivery costs before a live send. Never expose the OTP in logs, hardcode
   a code or weaken the mediated-proof check. This alternative still needs
   working discovery/link callbacks and participant action in the PHR app.
3. **M3:** use an authorized clinician's professional details, or obtain NHA's
   confirmation of a sandbox-only test requester and identifier vocabulary.
   The participant has reported that these details are not currently available.
   The four required requester fields are described in the next section;
   no publicly searchable identity or sample registration may be silently
   borrowed. The existing support draft now includes this precise question.
4. After these inputs, perform a scoped PHR consent approval and real encrypted
   transfer/read-back, then the assigned negative cases. Local clinical consent
   alone does not authorize PHR sharing or establish milestone completion.

## Controlled retry and midnight handoff — 13 September, 00:03 IST

**Current outcome: token generation returned 202; M2 linking and M3 exchange
are not yet complete.** This section supersedes the unrecorded-consent handoff
below. No patient identifiers, demographics, OTPs, tokens or clinical contents
are included in this evidence.

- Verified that the participant saved a new Clinical Review consent at
  **12 September 14:43:07 UTC**, expiring at **18:29:59 UTC / 23:59:59 IST**.
  Checked active consent and exact patient match immediately before the retry.
  Local clinical consent is not a substitute for transmission permission or
  separate PHR consent.
- The participant explicitly approved **one** retry of the pending HIP token
  operation. Preview safeguards passed. Applied the audited requeue and ran
  `run_once(ident=...)` for only the existing job, preserving REQUEST-ID
  `d613360a-99e5-5fc4-873c-b804d01dba8a` and its counters. The previous expired
  operation was not revived and the general worker was not started.
- At **18:25:41 UTC / 23:55:41 IST**, the HIP gateway log recorded
  `POST /api/hiecm/v3/token/generate-token` → **202**. The selected job completed
  with two total attempts and no stored failure. This is fresh acceptance
  evidence; it does not establish the original attempt's unknown HTTP status.
- At **18:29:05 UTC**, the selected link was still pending with no stored token
  or confirmation; no received content or transfer keys existed. No real token
  callback appeared in the inspected local access-log window after dispatch.
  This is a timestamped observation, not a claim about NHA's internal queue or
  a callback-delivery SLA.
- Rechecked at **18:33:03 UTC / 13 September 00:03:03 IST**: still no token
  or confirmation, and the midnight local consent was now explicitly inactive.
  Counts of other pending jobs remained unchanged.
- The public token callback accepted HTTPS and rejected an empty probe with
  **400**, as expected. Read-only bridge-services returned **200**, with the
  configured callback URL matching and both HIP/HIU services active. No bridge,
  credential, routing-header, security or callback-payload changes were made.
- Reopened a fresh Chrome tab after the old tab's browser-control attachment
  failed. Normal Keycloak doctor sign-in succeeded; the queue rendered without
  an error, and fresh status-only logs showed queue and critical-alert stream
  **200**. No password reset, certificate bypass or extra role was needed.

**Participant input still required:** midnight has passed and that local
consent has expired. The existing patient's renewal form is open in Chrome.
Review the actual channel, purpose and intended future expiry, then submit
only if consenting. The participant subsequently chose **Monday night**:
the form is now prepared with **14 September 2026**, meaning **23:59:59 IST**
under this form's existing conversion. The agent has not clicked Record consent.
No unnecessary ABHA OTP was requested, because the existing identity remains
verified. Enter any subsequently required OTP only in the browser.

M3 also remains blocked by incomplete requester registration: configure the
genuine or NHA-approved clinician name, registration number, identifier type
and registry URI in Admin → Users. Do not use a dev username, ABHA number,
client ID or invented medical registration as a substitute.

Next safe action: inspect metadata for any late callback. Do **not** issue a
third token attempt, extend a token lifetime, grant consent on the participant's
behalf or start the general worker. Any eventual link dispatch must still be
limited to the previously approved document and a valid token; clinical transfer
requires its separate consent/authorization checks. The updated linking-support
draft records the exact request ID and observed status for NHA tracing, but has
not been submitted.

Verification after this retry: **47 focused tests passed** for operational
metadata, HIP linking/recovery and PostgreSQL job leases. Two existing Pydantic
alias warnings remain. Ruff and `git diff --check` pass. The recovery helper's
description/error now says completed dispatch, not proven gateway acceptance;
its retry limits and authorization behavior are unchanged. These tests used
the isolated test database, not the participant's live sandbox rows.

### Where to obtain the M3 requester details

Checked the supplied `ABDM DOCS/M3_Dcoument_16_02_2026_2319bac7bf.docx`
(consent-request body table and examples) and NHA's public HPR guidance.

**Separate the wire contract from registry enrollment.** M3 v2.8 marks
`requester.name` and `identifier.{type,value,system}` required. HealthDoc's
current adapter obtains these from the active, facility-scoped staff profile;
it validates completeness and URI shape, **not live registry membership**.
The inspected M3 material does not establish that every sandbox request needs
a newly registered HPR account. Do not make HPR enrollment an unsupported
additional certification requirement.

1. **If a participating clinician is available:** obtain their permission and
   professional name, registration number and issuing registry details directly
   from them or the authorized hospital administrator. Use the identifier type
   for that registration and its actual issuer URI. Do not borrow an unrelated
   clinician's record from a public search. Configure the authorized requester
   in Admin → Users; preserve existing clinical authorship and do not relabel
   a dev account as a real clinician merely to pass validation.
2. **If the clinician needs an HPR identity:** NHA links the official
   [Healthcare Professionals Registry](https://abdm.gov.in/healthcare-professionals)
   to `https://hpr.abdm.gov.in/en`. Its
   [FAQ](https://abdm.gov.in/faqs) explains professional/council verification and
   the supporting registration/qualification documents. This is not a source
   of free shared test credentials or a way for a non-clinician to obtain a
   medical registration. Completion/approval by tomorrow is not guaranteed.
3. **If no clinician is available, as currently reported:** request a documented
   sandbox-only requester test identity or written confirmation of the allowed
   synthetic requester policy through the existing NHA sandbox support account.
   NHA lists `integration.support@nha.gov.in` for integration guidance in its
   [FAQ](https://abdm.gov.in/faqs). Ask specifically for the four requester
   fields, identifier vocabulary/registry URI, and permission to use them in
   the assigned M3 cases. This can accompany the existing missing-callback
   trace request; neither message has been sent by the agent.

The supplied documents illustrate `REGN01`, `REGNO1` and `REGNO` inconsistently;
their examples also vary in the displayed doctor name and registry URI. A
sample such as `MH1001` is not evidence of an authorized identity for HealthDoc.
No public shared M3 requester identity was verified in the primary sources
checked. Do not paste sample values into the participant workflow or weaken
the profile check simply to obtain HTTP 202. Local synthetic fixtures remain
valid test inputs, but are not evidence of a real sandbox exchange or approval.

## Doctor API repair and participant handoff — 12 September, 20:13 IST

**Doctor queue and critical-alert authorization are repaired and live-verified.**
This supersedes the unresolved 403 and browser-availability notes below.

- The browser's safe error identified `actor_not_provisioned`. Read-only
  Keycloak/app comparison found changed subjects for `dev.doctor`, `dev.admin`
  and `dev.receptionist`. Each old subject returned 404 in the current realm;
  exactly one enabled account matched the expected dev username/name and
  single expected role. Existing staff profiles were active in the seeded
  facility. This was identity mapping drift, not missing doctor permissions.
- Added `backend/scripts/repair_dev_identity.py`: preview-first, local-dev-only,
  three explicitly supported accounts, caller-supplied staff UUID and both
  reviewed subjects. It refuses stale/colliding mappings, existing old realm
  accounts, disabled or federated replacements and unexpected roles. Apply
  changes only the subject and update timestamp, with a same-transaction audit.
  No password, role, registration, facility, staff UUID or clinical FK is changed.
- Previewed then applied only those three mappings. No full seed rerun,
  migration, new account, consent grant or clinical-data rewrite occurred.
  Unit regressions verify field preservation and rollback on audit failure.
- Real Chrome doctor login/refresh now renders the queue without an error.
  Status-only backend logs verify `GET /api/v1/queue/worklist` **200** and
  `GET /api/v1/pathology/critical-alerts/stream` **200** after reconnect.
  An empty current queue is valid; no synthetic live critical alert was injected.
- Verification: **48 targeted repair/authentication/role-boundary/critical-alert
  tests passed** through `make test-pg` using the isolated test database;
  touched-file Ruff and whitespace checks pass. No full-project CI or live
  M2/M3 round trip is claimed. Source changes remain uncommitted.
- Browser navigation works again. The earlier approval failure was a usage
  limit, not a broken Chrome extension. If it returns, inspect the usage
  dashboard/reset time; eligible accounts can add credits. Do not disable
  approval checks or certificate validation. See [official usage guidance](https://learn.chatgpt.com/docs/pricing).

**Participant handoff (not a recorded grant):** exact ABHA search found one
existing patient. Metadata comparison confirms both identifiers supplied by
the participant match the existing active patient and a previous identity
verification is already recorded. Identifiers are deliberately omitted here.
No duplicate patient, ABHA rewrite or unnecessary OTP request was made.

The existing Chrome tab is at `https://localhost/consent`, prepared for that
patient with Clinical Review, decision by Patient and expiry **12 September
2026** (the form uses 23:59:59 local time). The channel remains the form's
default and must be reviewed for accuracy. **Record consent has not been
clicked.** The participant must review scope/channel/expiry and make the actual
decision. A local consent renewal does not require an ABHA login OTP and does
not grant PHR consent or prove M2/M3 completion. Requester registration details
and pending HIP linking still need their separate checks after renewal.

**Recurrence risk:** the development Keycloak service currently uses its
container-local database without a persistent data mount. Recreating it can
replace realm/user IDs while PostgreSQL keeps existing profiles. Do not use
this CLI as a general username-based login fallback or silently rebind other
accounts. Durable Keycloak storage needs a separate preservation/migration
step: attaching a new empty volume now would itself hide the current realm.
The running identity provider was not recreated during this repair.

## Browser follow-up — 12 September, 19:56 IST

**Status: running locally, live acceptance blocked.** This section supersedes
earlier statements about current tool availability and frontend verification.

- Docker showed the backend, frontend, Keycloak, nginx, cleanup worker and
  dependent storage services running. No full-stack rebuild, database reset,
  seed rerun or general outbound worker start was needed/performed.
- The existing Chrome tab pointed at a stale Keycloak endpoint and showed
  "Page not found". Opening `https://localhost` started a fresh sign-in.
  The documented `dev.doctor` test login completed and reached
  `/doctor/dashboard` with the Doctor role and its sidebar. No browser
  certificate exception or authentication guard was changed.
- **New unresolved blocker:** that dashboard displayed a permission error.
  Status-only nginx inspection confirmed HTTP 403 on `GET /queue/worklist`
  and `GET /pathology/critical-alerts/stream`. Both routes permit doctors in
  source. The local `dev.doctor` staff row exists, is active and has a subject,
  but its subject match with this browser session was **not verified**. Do
  not assume a role bug, rebind identities by username or rerun the full seed.
  A separate diagnostic password-grant attempt returned HTTP 400; it yielded
  no token and does not invalidate the successful browser PKCE login.
- **Fixed locally:** removed unsupported FIPS/compliance, complete-ABDM,
  hardcoded product-version and optional-PACS-ready wording from sign-in.
  The banner now explicitly says sandbox verification is in progress. New
  rendered-component tests cover these claims without changing login behavior.
  Known `actor_not_provisioned` / `user_deactivated` responses now explain the
  account-provisioning remedy without exposing server detail; an ordinary
  role denial still stays forbidden. Requester validation now correctly refers
  to all three registration fields, not "both". These copy fixes are **not**
  proof the doctor's 403 is repaired.
- Metadata rechecked at **14:18:55 UTC / 19:48:55 IST**: participant local
  consent still expired, requester incomplete, selected token callback missing,
  no received content or stored keys/tokens. No token retry, new consent
  request or clinical transmission was performed.

**Browser/tool stop:** attempting to open the ABDM workspace was refused by
the approval service because its usage limit was reached. No indirect browser
or credential workaround was used. The application remains running, but the
new copy and remaining flow could not be rechecked in the live browser.
Safe local source edits and tests continued. Fresh frontend evidence:
**112 tests pass**, typecheck, touched-file ESLint and production build pass.
The 19 backend staff-resolution/JWT regression tests also pass using test
doubles; they do not establish the cause of this live 403.

Next: restore approved browser access, reload the doctor page to read the
specific safe error, and compare the authenticated subject/realm role with
the existing app profile before any repair. Preserve existing staff IDs and
clinical attribution; do not grant extra roles or create a new identity to
hide this failure. Then resume the consent/requester and scoped M2/M3 steps
below. Participant consent/OTP/PHR approval and genuine requester details
cannot be supplied by the agent.

## Latest post-merge execution — 12 September, 19:38 IST

PR #556 is verified merged into main at `3514efef666005a0061cea0228c912c4e290d986`.
The follow-up work is on **`fix/abdm-live-operations`**, based on that revision.
Tool access resumed; the earlier usage-limit notes below are historical.
Merging the implementation does not establish a successful M2/M3 exchange.

### Completed in this follow-up

- **Restored the public callback tunnel.** Local health returned 200 while
  the public callback returned HTTP 530 / Cloudflare error 1033. The installed
  system daemon invoked only `cloudflared`, without a tunnel command/config.
  A separate user LaunchAgent, `com.healthdoc.abdm-tunnel`, now runs the
  existing tunnel UUID with its explicit existing private config. The system
  daemon, DNS, bridge registration, credentials and ingress were not changed.
- **Verified supervision and routing.** Four connector connections registered.
  A controlled launchd restart produced a new running PID; the public token
  callback returned 405 afterward. All 16 empty callback POST probes reached
  refusing endpoints; public health and docs still returned 404, as required
  by callback-only ingress. This proves reachability/refusal, **not** NHA-origin
  authentication, a delivered token or a clinical transfer. No reboot/logout
  test was performed. The user-level service needs a logged-in user, awake
  Mac, Docker and working network; it is not production high availability.
  Installation, restart and rollback: [tunnel operations](../infra/cloudflared/README.md).
- **Verified periodic cleanup.** Restarted only the existing cleanup-only
  container. Five consecutive successful passes were logged at approximately
  14:03:48, 14:04:48, 14:05:48, 14:06:48 and 14:07:48 UTC, each clearing zero
  items. No clinical records were removed. The general outbound worker was
  not started and the 18 unrelated notifications were not dispatched.
- **Hardened the read-only diagnostic tool and added regressions.** Details
  below. Repository-level script tests now also have an explicit CI step;
  backend pytest alone did not collect them.

`backend/scripts/abdm_operational_status.py` now provides these checks:

- `--requester-username` selects the actual operator rather than requiring the
  dev account. Profile readiness reuses the HIU validator (active, same
  facility, complete name/identifier/registry URI). Registry membership is
  still not established by syntax validation.
- Local consent reports patient match, purpose and lifecycle separately. A
  granted consent for someone else or a different purpose is not permission
  for this test. Null expiry follows the existing local consent model;
  future grants, expired and revoked records are not active.
- A token job marked done without a stored token is explicitly diagnosed as
  missing callback evidence, not NHA acceptance. Token presence does not imply
  confirmed linking; the existing token-use window is not extended.
- The tool reads metadata under a read-only transaction. It does not print
  patient/staff identifiers or requester values, renew consent, dispatch jobs,
  grant transmission authority or certify live exchange. The old ambiguous
  `local_consent_valid`/`dev_requester` output fields are replaced by structured
  `local_consent` and `requester` diagnostics. Update local consumers if any.

### Current live blockers and exact next order

Metadata rechecked at **14:07:54 UTC / 19:37:54 IST**: selected link pending,
no token or confirmation; token job done with one attempt but no captured
original acceptance status. The selected local consent matches the patient
and clinical-review purpose but is **expired**. The selected requester profile
is **incomplete**. No received-content rows, stored transfer keys or link tokens
exist. Restoring the tunnel did not itself replay the old callback.

1. **Participant action:** renew the local clinical-review consent in the
   application for the approved test patient/document. Do not extend the old
   row manually, backdate consent or treat this runbook as consent.
2. **Owner/clinician action:** in **Admin → Users**, configure the actual
   requester's complete name, genuine/NHA-approved professional registration
   number, identifier type and registry URI for this facility. Do not use an
   invented registration, ABHA number, bridge ID or client secret. A syntactic
   pass does not verify registry membership. Enter sensitive details in the
   application, not chat.
3. Recheck these prerequisites with the metadata tool, using the selected link,
   renewed consent and actual requester. Recheck clinical access and precise
   document/visit scope. Separate PHR approval remains required later.
4. Diagnose the preserved pending token request and decide a supported,
   explicitly authorized quota-safe recovery. This tool does not authorize
   one and a done job does not prove the original HTTP acceptance status.
   Keep its original correlation ID; do not blindly regenerate or drain the
   outbound queue. Inspect any real callback delivered after tunnel recovery
   before deciding whether another request is necessary.
5. Complete the M2 sequence below for the approved synthetic document, then
   the M3 request, **participant PHR approval**, receive/render/revoke/expiry
   sequence. The participant enters any OTP and approves consent personally.
   Update only cases with direct evidence; do not label preparatory tests as live.
6. Resolve assigned HI-type scope and the other cases in the supplied ledger.
   Invoice, ImmunizationRecord and HealthDocumentRecord remain separate
   implementation gaps, not covered by a WellnessRecord demonstration.

Verification in this follow-up: **679 targeted backend integration/FHIR/settings
tests passed**, six existing Pydantic alias warnings. The tests use an isolated
PostgreSQL database and mocked gateway traffic; they do not prove an NHA round
trip. **20 repository-level script tests passed**; touched-file Ruff, shell
syntax and whitespace checks passed. The full backend/frontend gates and GitHub CI
were not rerun for this local branch. Changes remain local and uncommitted.

**No new token generation, consent request, clinical transmission or milestone
declaration was performed.** The two user-input prerequisites above remain
blocking; live M2/M3 and certification must not be marked complete.

## Earlier execution update — 12 September, after implementation review

This section supersedes older statements below about crypto/PDF readiness.
Detailed implementation and evidence: [crypto/PDF/cleanup execution](abdm-crypto-pdf-cleanup-execution-2026-09-12.md).

1. **Crypto repaired and independently verified:** Bouncy Castle Curve25519
   replaces incompatible raw X25519. Published Fidelius vector matches exactly;
   fresh exchanges pass against the actual reference CLI in both directions,
   including point and X.509 keys. Docker/CI build the checksum-pinned helper.
2. **Embedded PDF support added:** consent-bound Binary/DocumentReference
   intake with document membership, type/size/hash checks; canvas-only browser
   preview. Real Keycloak/browser with explicitly synthetic ABDM responses
   proved rendering, no PDF script/link execution, and removal on refused
   access refresh. This is not an NHA transfer or live consent-revocation case.
3. **Independent cleanup deployed locally:** `--mode cleanup [--once]` never
   enters the outbound dispatcher. One-shot run succeeded with zero items;
   `abdm-cleanup` container was observed running. No original clinical records
   were erased. Repeated scheduled-pass log inspection remains pending.
4. **Read-only live preflight:** at **08:38:54 UTC / 14:08:54 IST**, selected
   link still pending, no token/confirmation; local consent invalid and all
   three dev requester registration fields absent. No received-content rows,
   stored transfer keys or link tokens. Eighteen unrelated notifications remain
   pending. Same configured credentials returned registry HTTP 200, bridge
   active/not blocklisted, matching URL, both HIP/HIU services active. Public
   token callback GET returned 405 (route exists). Public `/api/v1/health` 404
   is **expected** callback-only ingress, not an outage; local health is 200.
5. **No clinical live exchange sent.** Participant renewal, valid requester
   identity and unresolved linking still block steps 5–6 of the agreed plan.
   No new token generation, replay, consent grant or milestone declaration.

Verification: **1,816 backend + 14 script tests pass**, six pre-existing
Pydantic warnings; **108 frontend tests**, typecheck, touched-file lint and
production build pass. Targeted crypto/PDF/retention suite: **71 pass**.
PDF.js npm install audit: zero findings. BC 1.86 OSV query: zero known findings.
This is not a new whole-system vulnerability assessment. Default PR checker
selected no Python files; explicit touched-file checks are recorded separately.
Final crypto/cleanup recheck: **24 pass**; explicit application/config/status
PR check: **zero blockers, zero warnings**; touched Ruff and diff whitespace
checks pass. The full PostgreSQL gate was not repeated after the final
central-settings/logging/documentation refinements.

**Tool limitation:** subsequent privileged execution was rejected by the
approval service because the usage limit was reached. The requested 16-route
empty-callback probe and periodic cleanup-log read did not run. Do not infer
their results from earlier runs or bypass the rejection through another tool.

## Honest target

Target a **real, participant-approved sandbox exchange**, then complete the
applicable evidence matrix. Do not promise M2/M3 certification on 12 September:
NHA callback delivery, participant PHR approval, scope clarification and assessor
review are external dependencies. One WellnessRecord round trip is not all
M2/M3 cases and not all required HMIS document types.

Latest operational check: **12 September 04:19 UTC / 09:49 IST**. The existing
link is still pending, with no token or confirmation; its token job is done
with one attempt. **No HIU consent request or clinical transfer has been sent.**
The exact dispatch success HTTP status was not captured by the old client;
job completion alone does not prove NHA accepted it.

Final local regression: **1,794 backend tests + 14 script tests passed**;
76 migrations form a linear chain with head **0069**. The frontend passes
**106 tests**, typecheck and touched-file ESLint; **214** API calls match
OpenAPI. Six existing Pydantic alias warnings remain. The first full attempt
had one PostgreSQL SSL-upgrade fixture error before its test body ran; that
file passed 13/13 separately and the complete rerun passed without a code or
SSL-setting change. Its underlying intermittent connection cause is not proven.
The default PR checker selected no Python files, so explicit changed-file
checks were used instead (no blockers). Touched ABDM modules pass Ruff;
the expanded users-module check still reports nine pre-existing import/default
dependency warnings also present at HEAD, so whole-backend lint is not claimed
clean. The previously validated synthetic document had zero validator
errors/warnings. Neither local tests nor FHIR validation prove a live exchange.

## Authenticated portal inspection — 12 September

The owner completed portal login/CAPTCHA. Read-only inspection of the user
dashboard, account menu, Milestone 2/exit page and integrator dashboard found:

- Sandbox application approved for client `SBXID_053401`. The profile lists
  M1, M2 and M3 in its requested scope (alongside M4/Providers). This is not
  proof that every API operation has been accepted or milestones certified.
- Sandbox exit review and production approval remain pending. The milestone
  page asks for completion declarations, dates and supporting documents; it
  is not an API test runner. No checkboxes, dates or submission were changed.
- No request-ID search, callback-delivery log or retry control was visible in
  the inspected account pages. The integrator dashboard contains aggregate
  application statistics, not this client's request traces. Do not claim that
  a diagnostic feature cannot exist elsewhere; none was available here.
- No ticket, new generation request, bridge change or clinical transfer was
  submitted. A fresh status-only local read still shows pending/no token,
  missing requester metadata and the same 18 unrelated notification jobs.

The portal renders the client secret in plain text and its initial automatic
browser snapshot included it. Subsequent reads were redacted; it has not been
copied into this report or source files. Keep that snapshot private. Plan an
owner-controlled credential rotation separately; none was performed because
the current investigation explicitly uses the same configured secret.

Portal access is no longer a prerequisite. The next user-dependent steps are
renewed local consent, a genuine/NHA-approved clinician requester, participant
PHR approval and a quota-safe decision about the unresolved token request.

## Code gaps repaired in this investigation

- **HTTP success is explicit:** the client no longer follows redirects or
  accepts non-2xx as success. Token generation, context linking, HIU consent
  initiation, HIU data requests and receipt notification require documented
  HTTP 202. Protocol/authentication failures stop for inspection, not repeated
  retries. This does not reconstruct the old request's missing response trace.
- **HIU receipt status is correct:** a successful receiver notification sends
  `RECEIVED`, not the HIP sender's `TRANSFERRED`, with `OK`/`ERRORED` entry
  statuses. Encrypted-receive and durable retry tests cover the wire payload.
- **M3 requester identity is explicit:** admin user profiles now expose the
  professional registration identifier type and issuing registry URI alongside
  the existing registration number. A consent request snapshots the actual
  clinician identity; missing/changed/legacy-unspecified identities fail
  before dispatch. The doctor workspace explains the block. Migration **0069**
  has been applied to the local development and isolated test databases; no
  identity was invented or backfilled. This is not registry-membership proof.
- **One token operation per explicit document selection:** mixed HI types
  now become groups inside a single `patient[]` link request, following
  [NHA's HIP linking implementation](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/hip/hrp/link/hipInitiated/HIPLinkV3Service.java).
  Each care context still represents one finalized document. Exact retries
  preserve legacy operations and counters; changing the selection under an
  existing key is refused. This reduces avoidable generation per type; it
  neither extends the five-minute local use cap nor enables unlimited reuse
  across separate actions. It does not recover the already pending callback.

## Before touching the patient record

1. **Renew local clinical consent with the participant.** The previous grant
   **expired** on 11 September at 23:59 IST. Do not access clinical records,
   backdate consent or renew it automatically. Local access consent and SBX
   PHR sharing approval are separate decisions.
2. Keep the existing verified patient and single synthetic WellnessRecord.
   Do not recreate the patient/visit, alter source authorship, fabricate a
   medical registration number, or select the unapproved OPConsultation.
3. Keep callback hosting stable and Mac awake/unlocked while using the local
   tunnel. The observed connector is task-session based, not reboot-tested
   production hosting. Confirm `bridge.url`, active HIP/HIU registration and
   public callback reachability without exposing secrets.
4. **Resolve the pending request without blind regeneration.** Authenticated
   portal inspection found no request-level diagnostics in the available
   account/dashboard pages. Preserve REQUEST-ID
   `d613360a-99e5-5fc4-873c-b804d01dba8a`, dispatched on 11 September at
   12:40:42 UTC. Keep the
   [support draft](abdm-linking-support-draft-2026-09-11.md) as an escalation
   option, not a substitute for self-diagnosis. Same-secret session and
   registration checks passed; bridge and both services are active, with no
   observed service-specific URL override. This is not proof of linking
   acceptance or endpoint entitlement. Preserve both operations, counters and
   request IDs. Three token-generation **job attempts** occurred on
   11 September; these are not necessarily three HTTP calls. Midnight does
   not prove a rolling quota reset. Do not send another generation request,
   including an empty-body probe, without a supported, explicitly approved
   retry decision: even a refused request may consume quota.
5. No general queue consumer: 18 unrelated context notifications are pending.
   Dispatch only identifiers belonging to the explicitly approved test.
6. **Configure the real M3 requester:** Admin → Users → clinician profile.
   Enter the genuine registration number, its identifier type and actual
   issuing registry URI, or an identity explicitly issued/approved by NHA
   for sandbox testing. `dev.doctor` currently has none of these configured.
   Do not use a made-up number, facility ID, client ID, ABHA or example URI.
   Browser validation of an incomplete profile has been exercised without
   saving a false identity; successful live requester submission remains
   pending. The backend validates completeness, not professional eligibility.

## M2 acceptance sequence

1. Observe the real token callback for its exact request ID and accepted
   recipient/facility; store the token encrypted, never in logs/screenshots.
2. Within the existing local use window, dispatch that operation's exact
   `link_context` job. If the callback is late or the credential expired,
   investigate; do not extend a credential lifetime or reset a completed job.
3. Require NHA's successful `/api/v3/link/on_carecontext` acknowledgement and
   local **confirmed** state. A queued/done outbound job is insufficient.
4. Have the participant verify HealthDoc and the single labelled record in
   the SBX PHR app. Link visibility is not yet permission to transfer content.
5. Use the participant's PHR consent action to approve only the intended
   WellnessRecord/date interval. Capture consent ID, transaction ID, ACK and
   transfer status without identifiers or credentials in public evidence.
6. Require HIP transfer delivery and receipt notification, then verify the
   PHR renders the actual synthetic content. A successful HTTP upload alone
   is not a readable record.

## M3 acceptance sequence

1. Doctor → **ABDM external records** → verified patient → request consent
   for **WellnessRecord only**, covering the finalized document timestamp.
   Choose a short agreed expiry; do not select all types/facilities by default.
2. Dispatch only the corresponding `hiu_consent` job. Verify real on-init
   callback correlation and the consent request becoming visible in SBX PHR.
3. **Participant approves in the app themselves.** No simulated callback,
   direct database grant or borrowed account is an acceptable substitute.
4. Process exact consent notification/ACK and artefact-fetch jobs. Check the
   granted scope, dates, HIP and expiry, not merely the original requested scope.
5. Queue and dispatch the exact HIU data request. Require the real on-request
   transaction ID, inbound data push, successful authenticated decryption,
   patient/document scope checks and persisted received-record status.
6. Open the received record in the doctor browser and compare its content,
   timestamp and attribution with the approved synthetic source. Verify no
   unrelated OPConsultation or visit-wide content was received.
7. Participant revokes consent; verify further access/fetch is denied and
   retention/erasure follows the implemented policy. Repeat expiry and replay
   cases without manufacturing NHA notifications.
8. An internal HealthDoc HIP→HIU test proves a useful first exchange. Also run
   the assigned external-HIP/HIU interoperability cases; do not treat a self
   round trip as proof of every counterparty.

M3 can be investigated independently of HealthDoc's missing M2 callback **if**
the participant already has an explicitly approved synthetic/test document
linked by another sandbox HIP. Confirm that prerequisite in the SBX app first;
do not request unrelated real records simply to get a green transfer.

## Remaining release/certification gaps

- **Missing real callback / original rejection trace:** external dependency,
  not a proven client-secret fault. Do not brute-force tokens or payload variants.
- **Five supported HI types vs eight in the supplied HMIS FAQ:** Invoice,
  ImmunizationRecord and HealthDocumentRecord lack full production mappings.
  Obtain NHA scope confirmation; implement them from real clinical/billing
  source data plus frontend entry/review and validator tests if required.
- **PHR-initiated linking:** verify OTP relay configuration and delivery, plus
  discovery/init/confirm live cases if in the assigned matrix. The M2 document's
  link-confirm recipient-header discrepancy needs NHA clarification; do not
  relax HIP attribution by guess.
- **Gateway callback-origin security:** routing headers are not cryptographic
  authentication. Verify the NHA-supported Authorization/edge trust mechanism
  before production exposure; the current checks do not establish this.
- **Clinical identity:** the development-only account-ID exception for the
  approved synthetic WellnessRecord does not satisfy real practitioner
  registration requirements. Real records need genuine source identities.
- **Operations:** persistent callback hosting, bounded retries, delivery alerts,
  backup/recovery evidence and assessed vulnerability/clinical approval remain
  release requirements. A tunnel and green test suite do not replace them.

Update the [case ledger](abdm-milestone-case-ledger-2026-09-10.md) only with
case-specific live evidence. Keep raw PHI, `.env`, OTPs, tokens, private keys and
unredacted screenshots out of Git, tickets and shared reports.
