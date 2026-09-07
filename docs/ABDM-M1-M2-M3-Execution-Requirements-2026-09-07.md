# HealthDoc | ABDM M1, M2 and M3
## Execution steps, blockers and requirements

Prepared 7 September 2026 (IST). For the product owner, engineering team, infrastructure owner and sandbox demonstrator. Scope: HealthDoc as a Health Information Provider (HIP) and Health Information User (HIU), not a separate PHR/locker product.

### Can we perform all three now?

**Not as a completed milestone or certification demonstration.** M1's core OTP workflow can be attempted with an authorized, consenting sandbox participant. M2/M3 cannot complete a live round trip while the callback host is unavailable. Important product workflows are also unfinished.

| Milestone | Present capability | Current verdict |
|---|---|---|
| M1: ABHA identity | Reception enrolment/login panel; corrected encryption and response handling | Core trial is conditional. Real OTP verification and the full applicable NHA checklist are unproven. |
| M2: share records as HIP | Care-context API, callbacks, consent gate and encrypted transfer code | Blocked by public ingress and link-OTP delivery; staff linking tools and HIP-initiated flow need completion. |
| M3: request/use records as HIU | Consent/HI request APIs, callbacks, receive/decrypt code | Blocked by ingress; clinician viewer/import and durable recovery remain incomplete. |

### Evidence available today

- Local gates: 1,299 backend tests, 26 frontend tests, 14 script tests and 196 API contracts passed. TypeScript, frontend ESLint and production image build passed.
- Real Keycloak browser verification: 48/48 dashboards, 10/10 workflows, superadmin isolation, nine login/accessibility checks and four synthetic PDF checks passed. These are local functional checks, not ABDM interoperability evidence.
- Registered sandbox HIP/HIU services were active; gateway session/service lookup and the ABHA certificate endpoint answered successfully during the review.
- Public callback health was rechecked on 7 September and still returned HTTP 530 / Cloudflare error 1033.
- The reviewed local database had zero ABDM care contexts, links, HIP requests, HIU consent requests, HIU requests and received bundles. This says nothing about testing in another database.

Code branch: `fix/billing-abdm-readiness`. PR target: `staging` only. The previous billing/nursing baseline is already in staging through PR #531. This document does not authorize a merge or direct promotion to main.

<!-- pagebreak -->
# 1. Requirements before a live attempt

Assign an actual owner to every row. A populated environment variable is not evidence that the service behind it works.

| Requirement | Owner | Evidence required to proceed |
|---|---|---|
| Current NHA M1/M2/M3 checklist and registered scope | Product owner / NHA liaison | Assigned test cases, required linking methods, HI types, evidence format and demo booking confirmed by NHA. |
| Sandbox participant and phone | Demonstrator / participant | Explicit agreement to testing; participant enters their own OTP through the product. Use coherent synthetic clinical records. |
| Reference ABHA app, HIP and HIU | NHA liaison / QA | Working test accounts and app versions. Reference-HIU access can be requested through NHA support; reference HIP/EMRSBX access is described in sandbox documentation. [S1] |
| Existing public tunnel | Infrastructure owner | Healthy connector; valid public TLS; registered hostname reaches this backend through nginx; restart does not break it. Current blocker: 1033. |
| Callback origin controls | Security / infrastructure | Agreed gateway and external-HIP ingress policy; no interactive login or unknown private header blocking callbacks. |
| Patient-initiated link OTP relay | Backend / infrastructure | Real HTTPS delivery endpoint and protected token; successful delivery plus wrong-code, expiry and retry-limit tests. Both settings were absent in the review. |
| Facility and service mapping | Backend / administrator | Configured HIP ID resolves to the correct local facility; HIU ID identifies the registered receiving service. Independently verify any required HFR registration. |
| Clinical records and FHIR mapping | Clinical lead / backend | Signed/complete records for supported HI types; actual outgoing documents validate against NHA's required NRCeS package. |
| Review and demonstration runtime | Reviewer / release owner | PR checks and review pass; approved staging code is built with correct public settings. Preserve feature → staging → main policy. |

**No secret belongs in this document:** client secret, access/refresh tokens, OTP, Aadhaar, raw ABHA identifiers, private keys and unredacted clinical data must stay out of tickets, git, screenshots and shared recordings.

NHA acceptance is external: implemented functionality must be demonstrated, functional/security assessment completed and required exit evidence submitted. Confirm the current process with NHA; local test counts do not replace it. [S1]

<!-- pagebreak -->
# 2. Configuration and preflight

Use only the sandbox environment. The supplied directory contains eight collections, production environments and a hardcoded production request. Do not run the complete pack blindly.

| Setting / concept | Required value or rule |
|---|---|
| Gateway base | `https://dev.abdm.gov.in` |
| ABHA API base | `https://abhasbx.abdm.gov.in/abha/api` |
| Consent manager | `X-CM-ID: sbx` |
| Public callback origin | `https://abdm.healthdoc.world`; must actually reach the app |
| Gateway identity | Securely configured `ABDM_CLIENT_ID` / `ABDM_CLIENT_SECRET` |
| Service identity | `ABDM_HIP_ID`, `ABDM_HIU_ID`, `ABDM_HFR_FACILITY_ID`; validate registration and local mapping, never use placeholders |
| M3 push address | `ABDM_HIU_CALLBACK_BASE_URL`; public HTTPS address for the receiving service |
| Link OTP delivery | `ABDM_LINK_OTP_DELIVERY_URL` and `ABDM_LINK_OTP_DELIVERY_TOKEN` |
| M1 public key | `ABDM_PUBLIC_KEY_PEM`; match the live ABHA certificate and its declared encryption algorithm |

From the repository root:

```bash
make ps
python3 scripts/check_abdm_collections.py
./scripts/abdm_sandbox.sh token
./scripts/abdm_sandbox.sh services
./scripts/abdm_sandbox.sh doctor https://abdm.healthdoc.world
```

The first two sandbox commands check existing registration; do not recreate it unnecessarily. Never enable shell tracing or share raw command output without reviewing it. The doctor command sends empty probes: a rejection establishes reachability only. HTTP 530/1033, 502, 404 or acceptance of an empty callback are stop conditions. After repair, verify an actual correctly correlated callback arrives.

### Do not mix these credentials or IDs

- HealthDoc staff APIs below use a HealthDoc Keycloak bearer token and local row UUIDs. Creates require an Idempotency-Key; its presence alone does not prove safe replay.
- Gateway calls use the ABDM session credential plus the v3 identifying headers. Do not use the client secret as a bearer token.
- An ABHA account token from M1 is not the HIP X-LINK-TOKEN. Obtain a link token through its intended generate-token/callback flow.
- Official callbacks use `/api/v3/...`, not `/api/v1/abdm/...` private legacy callbacks. Published identifying headers are not cryptographic proof of origin. [S2]

<!-- pagebreak -->
# 3. M1 — ABHA creation and verification

**Attempt status:** core workflow exists; needs a consenting participant, valid sandbox setup and actual execution. An M1-only outbound OTP trial does not need the HIP/HIU tunnel, but profile-share/other callback-based cases do.

1. Sign in as an authorized receptionist. Open `/receptionist/registration`, search for the person and select the correct synthetic local patient record. Avoid duplicate patient registration.
2. Open the ABHA panel. Prefer verifying an existing ABHA when suitable; do not create an unnecessary identity just for a demonstration.
3. Choose the existing-number flow, request the OTP and let the participant enter it. HealthDoc calls its login request/verify APIs and correlates the ABDM transaction with a facility-scoped local session.
4. Confirm success is based on `authResult: success` and one active account. Failed, inactive or ambiguous results must not bind an identity. A fresh reload must show the same person's verified identity/address.
5. If Aadhaar enrolment is required by the assigned case, use the new-account flow with the participant's explicit agreement. Confirm a returned address list does not cause an error or an arbitrary address selection.
6. Exercise wrong/expired OTP, retry, duplicate identity on another patient, wrong role/facility and safe error messages. No failed verification may persist an identity binding.
7. Capture redacted UI evidence and correlation IDs. Do not capture an account token, Aadhaar or OTP in the browser/network export.

### HealthDoc API map

```text
POST /api/v1/abdm/abha/login/request-otp
POST /api/v1/abdm/abha/login/verify-otp
POST /api/v1/abdm/abha/enrol/aadhaar/request-otp
POST /api/v1/abdm/abha/enrol/aadhaar/verify-otp
```

Use the existing UI rather than assembling raw Aadhaar requests in Postman. The fixes use the algorithm declared by the official public-certificate endpoint; national mobile digits and encrypted OTP are different wire fields. [S3]

### What prevents full M1 completion

Complete product workflows for mobile-verification continuation, address selection/creation, card/QR/profile download and any additional mandatory methods are not established. Obtain NHA's applicable checklist, map every case to a UI path, then build and verify each missing one. A manual Postman result does not establish a working HealthDoc workflow.

**Exit evidence:** correct identity persisted and read back, negative cases passed, every assigned mandatory M1 case executed, and NHA review requested with redacted evidence. The core OTP trial alone is not full M1 acceptance.

<!-- pagebreak -->
# 4. M2 — HealthDoc as HIP

**Do not start the round trip until public ingress and the real link-OTP relay work.** The sequence below is a technical trial of the implemented patient-initiated route, not a claim that every required linking mode is complete.

1. Create coherent synthetic encounters, prescriptions and released results for the verified participant. Select the supported HI types required for the demo. No fixture chart may stand in for a clinical record.
2. Register care contexts. Currently this is API-only setup by an authorized doctor/admin, not a completed staff UI:

```text
POST /api/v1/abdm/hip/care-contexts
Authorization: Bearer <HealthDoc staff token>
Idempotency-Key: <unique request key>

{
  "patient_id": "<actual local patient UUID>",
  "visit_id": "<actual local visit UUID>",
  "reference": "<unique care-context reference>",
  "display": "<meaningful record description>",
  "hi_type": "Prescription"
}
```

3. In the participant's sandbox ABHA app, discover the registered HIP, select the matching records and initiate linking. Complete the delivered OTP. Confirm both the app and HealthDoc show the same confirmed context link.
4. Through the reference HIU, request limited access. The participant grants consent in their app. Observe HIP consent notification and acknowledgement, followed by the health-information request and acknowledgement.
5. Verify encrypted data is pushed to the requesting HIU, decrypted and displayed there. Check completion notification and matching request/transaction/context IDs. Validate the actual sent FHIR document, not just repository sample bundles.
6. Create a later record for an already confirmed link and exercise the care-context notification path where applicable. Test narrowed dates/types, revoked/expired consent, wrong context/facility, duplicate requests and transfer interruption.

### Build requirements, not operator workarounds

- Add staff care-context/link management or an explicitly approved clinical-event producer.
- Finish HIP-initiated linking when required: application initiation, correlated pending-link state, token callback and link dispatch. The current gateway helper has no application caller. A standalone Postman generate-token request will not create the pending state its callback needs.
- Validate required notification, opt-out and retention behaviours against the assigned NHA cases; do not invent their policy or claim them tested.

**Exit evidence:** correct participant/context link, consent-scoped encrypted transfer and reference-HIU display, validated clinical content, required negative cases and all assigned linking methods proven. A callback HTTP 200 or a generated token alone is insufficient.

<!-- pagebreak -->
# 5. M3 — HealthDoc as HIU

**Current product gap:** staff APIs exist, but no complete clinician request/view/import workflow was found. Receiving plaintext onto an outbox is not a usable medical-record viewer.

1. At the reference HIP, create and link records for the same consenting test participant. Self-exchange between two HealthDoc roles alone does not prove interoperability with another implementation.
2. As a HealthDoc doctor/admin, create a consent request through the staff API. All angle-bracket values below are placeholders, not runnable test data:

```text
POST /api/v1/abdm/hiu/consent-requests
Authorization: Bearer <HealthDoc staff token>
Idempotency-Key: <unique request key>

{
  "patient_id": "<actual local patient UUID>",
  "abha_address": "<participant's verified sandbox address>",
  "purpose_code": "CAREMGT",
  "hi_types": ["Prescription"],
  "date_range_from": "<UTC ISO timestamp ending Z>",
  "date_range_to": "<UTC ISO timestamp ending Z>",
  "requested_expiry": "<future UTC ISO timestamp ending Z>"
}
```

3. Save the local request UUID. The participant grants consent in their app. Observe on-init, consent notification/acknowledgement and artefact fetch. Read the granted artefacts:

```text
GET /api/v1/abdm/hiu/consent-requests/{local_request_id}/artefacts
POST /api/v1/abdm/hiu/artefacts/{local_artefact_id}/health-information
```

4. Use the local artefact row UUID, not its external consent ID. HealthDoc must request the granted range, which may be narrower than the original request. Only CAREMGT is currently supported; other purposes now fail validation.
5. Confirm the external HIP pushes to `/api/v3/hiu/health-information/transfer`; verify transaction correlation, authenticated decryption, receipt/checksum persistence and completion notification.
6. Complete the missing clinician viewer/import leg. Records must be scoped to the correct facility, patient and permission; define access logging, persistence and retention with the responsible owners. Do not expose queued plaintext through an ad-hoc debug endpoint.
7. Test denial, expiry/revocation, tampering, duplicate/paged push, wrong transaction/facility, key cleanup and restart/retry recovery. No successful receipt may authorize access after consent ends.

**Exit evidence:** participant-approved consent, interoperable data retrieval, correct clinician display/use, scope and expiry controls, and every assigned mandatory M3 case passed. A received-bundle count is not full M3 completion.

<!-- pagebreak -->
# 6. Engineering completion and execution order

These are project tasks, not an official NHA case list. Do not mark a task complete merely because a route exists.

| Priority / task | Owner | Definition of done |
|---|---|---|
| P0: restore callback ingress | Infrastructure | Stable public TLS/origin; legitimate correlated callbacks accepted; invalid probes refused. |
| P0: freeze applicable scope | Product / NHA liaison | Current assigned M1–M3 cases mapped to implemented UI/API and missing work. |
| P0: link-OTP delivery | Backend / infrastructure | Real delivery, expiry, wrong-code and lockout tests; secrets protected. |
| P1: applicable M1 gaps | Frontend / backend | Required mobile/address/card/profile cases complete through the product, with failure handling and read-back. |
| P1: M2 context/link tools | Frontend / backend | Real records create/manage contexts; required HIP-initiated state and callbacks wired; participant sees correct links. |
| P1: M3 clinician workflow | Frontend / backend / clinical lead | Request consent, observe status, retrieve and safely view/use records; scoped storage/consumer and access audit. |
| P1: durable delivery and cleanup | Backend / security | Durable retry/replay and restart recovery; no duplicate side effects; agreed expiry/erasure behaviour demonstrably enforced. |
| P1: actual FHIR validation | Clinical lead / QA | Each demonstrated HI type validates with NHA's required profiles, and content matches the source clinical record. |
| P2: review/evidence submission | Release owner / QA | Approved staging build, all assigned cases evidenced, remaining failures declared, NHA review arranged. |

### Suggested session plan after prerequisites turn green

1. Preflight and access checks: allow 30–60 minutes.
2. Core M1 participant-led trial: allow 1–2 hours including negative cases.
3. M2 reference-HIU exchange: allow 2–3 hours after context/link preparation.
4. M3 reference-HIP exchange: allow 2–3 hours after the clinician workflow is built.
5. Evidence review: allow 1 hour, with time reserved for gateway/counterparty delays.

These are planning allowances for an attempt, not completion promises. If a prerequisite is red, spend the session fixing that prerequisite; do not manufacture a callback, OTP or successful record to continue the demo.

**Realistic target:** the known product gaps provisionally require 3–7 engineering days after scope is agreed, plus live sandbox regression. That estimate may expand with the assigned test cases. NHA acceptance and production access have their own external schedule. All three cannot honestly be promised today.

<!-- pagebreak -->
# 7. Evidence, review and reference checklist

### Evidence record for every assigned case

Capture case ID, milestone, source commit, environment, role, expected result, actual result, pass/fail/blocked, redacted screenshot, sanitized request/callback IDs, timestamps and relevant FHIR validation output. Preserve proof of both the successful path and the refusal path. Never attach an unredacted HAR or raw patient bundle to a public PR.

Suggested evidence index columns:

```text
NHA case | M1/M2/M3 | commit | role | expected | actual
status   | screenshot | request/transaction IDs | validator result
owner    | outstanding defect / blocker
```

### Submission sequence

1. Review the feature PR into staging and its actual CI results. Do not bypass failed checks or merge directly into main.
2. Build the approved staging revision and record its SHA. Run PostgreSQL tests before browser suites, not concurrently.
3. Execute the assigned NHA cases with the participant and reference applications. Mark missing or failed cases honestly.
4. Demonstrate implemented functionality to NHA and follow the current functional/security assessment and sandbox-exit instructions. Confirm the required reports, undertakings and review stages with the assigned team. [S1]
5. Request production promotion separately: staging → main only, after review and operational readiness. Creating this PR does not merge it or certify ABDM.

### Sources and limits

[S1] NHA official FAQ — reference applications and sandbox-exit process. Rechecked 7 September 2026 using indexed official content; direct page rendering was limited.
https://abdm.gov.in/FAQ

[S2] NHA ABDM wrapper — official v3 callback path constants. Local wire comparisons also used the supplied collection pack.
https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/common/constants/GatewayURL.java

[S3] Official ABHA public-certificate endpoint — observed during the live read-only review. Algorithm: RSA/ECB/OAEPWithSHA-1AndMGF1Padding.
https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate

[S4] Official sandbox portal — obtain the current checklist, support and demonstration instructions from the registered account. Its full current test sheet was not retrievable in this review. A search-result mirror was not treated as authority for mandatory scope.
https://sandbox.abdm.gov.in/sandbox/v3/

Project evidence: `docs/billing-abdm-readiness-2026-09-06.md`; local strict run `billing-abdm-final-20260907`. The supplied Postman pack contains 398 requests; 23 configured outbound paths match, but that is not full payload or certification coverage. Its environment files and examples may contain secrets or personal data and remain outside the PR.
