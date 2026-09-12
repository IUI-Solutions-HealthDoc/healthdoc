# M2/M3: next-day execution gates — 12 September 2026

## Latest execution update — 12 September, after implementation review

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
