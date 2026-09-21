# ABDM M1–M3 supplied test-case execution ledger

Date: 10 September 2026. Initial baseline: `main` at `23c89e0`.
Live OTP fix: `fix/abdm-otp-live-verification`, based on `658e791`.

Status: live acceptance NOT COMPLETE. See [preflight evidence and blockers](abdm-live-preflight-2026-09-10.md).

**21 September consolidation note:** the live observations below were recorded
by the preceding operator; this publication does not claim they were repeated.
The later restoration/0082 entries supersede the earlier 0079/502 preflight,
which is retained as dated history. A subsequent read-only public callback GET
again returned 405. The owner reports a new support ticket submitted; its number
and response remain unverified. Local patient identifiers have been redacted
from this published ledger. M1 enrolment/profile credentials must not be assumed
interchangeable with a HIP link token; successful identity binding is not
clinical-sharing consent or M2/M3 completion.

**21 September, ~11:54 UTC Create ABHA (new Aadhaar):** enrol request-otp **200**.
First verify-otp **400** (REQUEST-ID `e1839499-a83f-465e-9401-95accb233907`, no
`ABDM-NNNN`) without the communication-mobile override. Second verify-otp **200**
after the participant entered a 10-digit mobile override. Desk shows “ABHA
verified and linked” with a 14-digit hyphenated number and a PHR address.
On the participant-approved new chart (identifier withheld): `identity_status=verified`, ABHA bound,
encrypted linking token stored. Identifiers not recorded. **No M2/M3 case is
marked passed.** Worker remains stopped.

**21 September, ~11:38 UTC Aadhaar login OTP:** `POST /abha/login/request-otp`
**200** (after a 401 from the earlier session drop), participant-entered OTP,
`POST /abha/login/verify-otp` **409** `duplicate_abha`. ABDM accepted the OTP;
HealthDoc refused to bind that ABHA onto the new unlinked chart because it is
already on the earlier chart. Desk showed the generic 409 toast (reload copy);
`duplicate_abha` is now mapped to an explicit already-linked message. Identifier
not recorded. **No M2/M3 case is marked passed.** Worker remains stopped.

**21 September, ~11:25 UTC enrolment OTP refusal:** participant typed Aadhaar
on Create ABHA and Send OTP. Local API `POST /abha/enrol/aadhaar/request-otp`
returned 502 `abdm_rejected`. Upstream ABHA host returned **400** on
`/v3/enrollment/request/otp`; REQUEST-ID `63477bdf-800b-427b-9f02-870dd1258cc6`;
logged fields `loginId`, no `ABDM-NNNN` code. Desk toast is the generic
`abdm_rejected` copy. This is the enrol path for a **new** ABHA; retrying
Create ABHA with the same Aadhaar is expected to keep failing if that Aadhaar
already has an ABHA. Next runnable row is existing-ABHA via Aadhaar
(`login/request-otp`, scopes `abha-login` + `aadhaar-verify`). Identifier not
recorded. **No M2/M3 case is marked passed.** Worker remains stopped.

**21 September, ~11:15 UTC Aadhaar/profile desk pass:** new unlinked
registration chart opened (Create ABHA selected). No Aadhaar was sent to ABDM
in this pass. Local 11-digit and letter inputs mark the Aadhaar field invalid
and keep Send OTP disabled; the performance log shows no enrol/login request.
Navbar Hindi translates chrome only; ABHA identity copy stays English. Print
Patient Card is the local UHID card and states it encodes no Aadhaar/ABHA.
Enrol still hardcodes `consent code abha-enrollment` with no desk checkbox.
No NHA ABHA card/profile download route exists. Live Aadhaar OTP (enrol and
existing-ABHA via Aadhaar) is waiting on participant-entered Aadhaar and OTP.
**No M2/M3 case is marked passed.** Worker remains stopped.

**21 September, 10:51 UTC update:** local origin restored (alembic **0082**);
public token callback is **405** on GET, not 502. Synthetic public probes
returned 400 `missing_abdm_headers` and 404 `link_not_found`. Read-only
bridge-services **200**, HIP/HIU active, callback URL unchanged. Existing-ABHA
mobile OTP request **200** at 10:46:19 UTC and verify **200** at 10:47:40 UTC
(participant-entered OTP; identity bound in the existing chart). M2 still has
no stored link token for REQUEST-ID `d613360a-99e5-5fc4-873c-b804d01dba8a`.
Outbound worker remains stopped (22 `context_notify` pending, 1 expired
`link_context` unrepaired). `dev.doctor` requester fields remain empty. Copy-ready
follow-up ticket: [abdm-support-ticket-ready-2026-09-21.md](abdm-support-ticket-ready-2026-09-21.md).
**No M2/M3 case is marked passed.**

**12 September, 04:04 UTC update:** the pending token request below still has
no callback or token. Local consent expired at 23:59 IST on 11 September;
renewal, a genuine/NHA-approved clinician requester profile and participant
PHR approval remain prerequisites. HTTP-success checks, HIU receipt status,
requester snapshots/admin validation and mixed-type grouped linking have been
repaired and regression-tested. **No live case status has changed.** See the
[current runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md) for final gate results.

**11 September, 17:57 UTC update:** 523 ABDM integration tests and 27 separate
FHIR/settings tests pass. Ten more documented callback-header mismatches and
unsafe token/auth retry behaviour were corrected. A new browser-queued link
for the same approved synthetic WellnessRecord is **pending without a token
callback** (REQUEST-ID `d613360a-99e5-5fc4-873c-b804d01dba8a`, dispatched 12:40 UTC).
The old expired operation remains unchanged. The same secret still passes
session/bridge checks; callback probes reach the correct backend. No HIU request
or clinical transfer has been sent, and **no M2/M3 case is now marked passed**.
See the [12 September runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md).

This indexes 118 rows carrying a test-case ID from the supplied M1 v1.2, M2 and M3 workbooks. It is **not 118 mandatory tests**, not a completeness claim for all downloaded APIs, and not a pass percentage. Applicability depends on integrator category and the selected flow. Blank row labels and duplicated source IDs are preserved; identify evidence by workbook + sheet + row as well as case ID. The M1 API-only appendix has entries without case IDs and is not counted here.

All live statuses started as **NOT RUN**. Existing-number mobile OTP and tagging remain **PARTIAL**. The 21 Sep Aadhaar desk pass adds **PASS** for the Create ABHA control, **PARTIAL** for local Aadhaar collection/error, and **GAP** where the product has no consent checkbox, no NHA ABHA card/profile download, and no demographic/biometric/find-by-mobile flows. Gateway probes, unit tests and the user's report of PHR registration are not substitutes for end-to-end cases. Do not change a status without case-specific evidence. Never put ABHA/Aadhaar numbers, OTPs, tokens, private keys or identifiable clinical screenshots in this file.

The November 2025 FAQ, p. 2, requires eight HI types for HMIS; the older M3 workbook lists seven types and an 'any one' branch. Treat that conflict as needing NHA scope confirmation, not permission to certify only one type. HealthDoc currently supports only five types. The separate PHR/Locker workbook is not automatically in scope for an HMIS using NHA's PHR app.

Historical preparation (11 September): participant-approved local consent was
valid through 23:59 IST on 11 September and is now expired. The original test visit is completed
with one labelled synthetic observation and no diagnoses/orders/prescriptions.
The source author's missing registration is handled only for the explicitly
allowlisted development WellnessRecord, using its existing local account ID
typed as `AN`, not a medical licence. Name and source authorship are preserved.
The actual export also exposed a missing ABHA identifier type and an incorrect
UHID namespace; both were fixed and regression-tested.

The actual rebuilt document passes the official HL7 6.9.12 validator against
NRCeS 6.5.0 with **0 errors / 0 warnings**, networking disabled and `-tx n/a`.
There are **120 passing focused tests via `make test-pg`** after these changes,
including received-record identity/consent checks. The separate
consent-page fix retains its earlier 100-test/frontend browser evidence.

The live doctor browser queued only the synthetic WellnessRecord for linking;
OPConsultation remains unlinked. After explicit transmission approval, NHA's
first token callback received 400. Fixed the two linking callback header
contracts and executed one guarded recovery with the original request ID:
NHA's token callback received **202** and the token was stored encrypted.
The following link operation did not complete: gateway rejection, session
HTTP 500, then authentication failure. The local use window expired and the
exact link's credential was cleared; the link is **expired**, not confirmed.
Final follow-up: **446 ABDM integration tests passed** (19 deselected, six
Pydantic alias warnings), plus **27 FHIR-builder/settings tests passed**.
Chrome confirms the exact WellnessRecord is expired, the other document is
not linked, and no consent requests exist. Session/bridge read-back is 200,
both HIP/HIU registrations are active, and the callback tunnel was restored.
These do not establish milestone acceptance. See the preflight for precise limits
on retained error evidence and the fresh-attempt prerequisites.
No HIU request or clinical payload was sent. The 18 context-notify jobs remain
unprocessed and the general worker is stopped. See the preflight report for
correlation IDs, validation hashes, the secret-rotation follow-up and the exact
resume sequence. **No M2/M3 case is marked passed** by local validation or a
queued operation; do not recreate the participant, visit or document.

## M1

Source: [Copy_of_M1_ABHA_CREATION_AND_VERIFICATION_WITH_APIS_UPDATED_V1_2_7_Aug_1_58de4446bc.xlsx](../ABDM%20DOCS/Copy_of_M1_ABHA_CREATION_AND_VERIFICATION_WITH_APIS_UPDATED_V1_2_7_Aug_1_58de4446bc.xlsx), sheet **ABHA CREATION AND VERIFICATION**.

| Row | Case ID | Function / scenario | Source applicability label | Live result | Evidence |
|---|---|---|---|---|---|
| 22 | CRT_ABHA_101 | Create ABHA Option | Mandatory | PASS | 21 Sep 2026 desk: Create ABHA is present, selectable, and switches the identifier to Aadhaar on a new unlinked chart. |
| 23 | CRT_ABHA_102 | Consent collection | Mandatory | GAP | No desk consent checkbox. Enrol payload still hardcodes `consent: {code: "abha-enrollment", version: "1.4"}` with no patient-facing capture. |
| 24 | CRT_ABHA_103 | Suggestions:- Consent collection should be multilingual | Optional | GAP | Navbar Hindi translates chrome only. Identity panel and the missing consent copy stay English. |
| 25 | CRT_ABHA_104 | Aadhaar collection and Error Message | Mandatory | PARTIAL | Local 11-digit/letter invalidation as before. Live enrol Send OTP: ABDM HTTP 400 on `loginId` (REQUEST-ID `63477bdf-800b-427b-9f02-870dd1258cc6`); desk shows generic `abdm_rejected` toast, not the gateway message. |
| 26 | CRT_ABHA_105 | Aadhaar OTP Collection | Mandatory | PASS | First Aadhaar (already had ABHA): enrol request 502/400, no OTP field. New Aadhaar: enrol request-otp **200**, OTP field shown, participant entered OTP. |
| 27 | CRT_ABHA_106 | Resend OTP | Mandatory | NOT RUN | — |
| 28 | CRT_ABHA_107 | OTP based Aadhaar Authentication | Mandatory | PASS | Enrol verify-otp **200** after communication-mobile override; identity bound. First verify without mobile was 400 (REQUEST-ID `e1839499-a83f-465e-9401-95accb233907`). |
| 29 | CRT_ABHA_108 | Communication Mobile Number verification-I | Optional | PARTIAL | Enrol verify requires the optional “Mobile override” for this sandbox Aadhaar; without it verify was 400. Not a separate mobile OTP. |
| 30 | CRT_ABHA_109 | Communication Mobile Number verification-II | Mandatory | PARTIAL | Participant supplied a 10-digit mobile on enrol verify; ABDM then returned 200. No separate `mobile-verify` continuation OTP. |
| 31 | CRT_ABHA_112 | Suggested ABHA Address | Mandatory for Private /Government (Optional for integrated program using demo auth as they have default ABHA address generated) | GAP | No suggested-address picker after enrolment. |
| 32 | CRT_ABHA_113 | Display of ABHA Number | Mandatory | PASS | After enrol, desk shows “ABHA verified and linked” with a 14-digit hyphenated number and a PHR address. Values not copied into this ledger. |
| 33 | CRT_ABHA_114 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | GAP | Print Patient Card is the local UHID card; on-screen note: no Aadhaar/ABHA encoded. No NHA ABHA-card generator. |
| 34 | CRT_ABHA_115 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_114 or CRT_ABHA_115 is mandatory for Governement Optional for Private | GAP | No ABHA profile/card download API or viewer. |
| 36 | CRT_ABHA_201 | Create ABHA Option | Optional | PASS | Same Create ABHA control. Biometric branch is CRT_ABHA_205 GAP. |
| 37 | CRT_ABHA_202 | Consent collection | Optional | GAP | Same missing desk consent as CRT_ABHA_102. |
| 38 | CRT_ABHA_203 | Suggestions:- Consent collection should be multilingual | Optional | GAP | Same as CRT_ABHA_103. |
| 39 | CRT_ABHA_204 | Aadhaar collection and Error Message | Optional | PARTIAL | Same local collection/error as CRT_ABHA_104. |
| 40 | CRT_ABHA_205 | Biometric based Aadhaar Authentication | Optional | GAP | No biometric capture or Aadhaar-bio API on the desk. |
| 41 | CRT_ABHA_206 | Communication Mobile Number verification-I | Optional | NOT RUN | — |
| 42 | CRT_ABHA_207 | Communication Mobile Number verification-II | Optional | NOT RUN | — |
| 43 | CRT_ABHA_208 | Display of ABHA Number | Optional | NOT RUN | — |
| 44 | CRT_ABHA_209 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | GAP | Same local UHID card as CRT_ABHA_114; no NHA ABHA card. |
| 45 | CRT_ABHA_210 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_209 or CRT_ABHA_210 is mandatory for Governement Optional for Private | GAP | Same as CRT_ABHA_115. |
| 47 | CRT_ABHA_301 | Create ABHA Option | Mandatory | PASS | Same Create ABHA control as CRT_ABHA_101. Demographic-auth branch is a separate gap (305). |
| 48 | CRT_ABHA_302 | Consent collection | Mandatory | GAP | Same missing desk consent as CRT_ABHA_102. |
| 49 | CRT_ABHA_303 | Suggestions:- Consent collection should be multilingual | Optional | GAP | Same as CRT_ABHA_103. |
| 50 | CRT_ABHA_304 | Aadhaar collection and Error Message | Mandatory | PARTIAL | Same local collection/error as CRT_ABHA_104. Demographic-auth error path not present. |
| 51 | CRT_ABHA_305 | Demographic Information based authentication | Mandatory | GAP | No demographic-auth enrolment path in identity APIs or UI. |
| 52 | CRT_ABHA_306 | Profile Completion | Mandatory | GAP | No ABHA profile-completion wizard after enrolment. |
| 53 | CRT_ABHA_307 | Display of ABHA Number | Mandatory | NOT RUN | — |
| 54 | CRT_ABHA_308 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | GAP | Same as CRT_ABHA_114. |
| 55 | CRT_ABHA_309 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_308 or CRT_ABHA_309 is mandatory for Governement Optional for Private | GAP | Same as CRT_ABHA_115. |
| 57 | CRT_ABHA_401 | Create ABHA Option | Optional | NOT RUN | — |
| 58 | CRT_ABHA_402 | Consent Collection | Optional | NOT RUN | — |
| 59 | CRT_ABHA_403 | Communication Mobile Number | Optional | NOT RUN | — |
| 60 | CRT_ABHA_404 | Mobile Number Verification | Optional | NOT RUN | — |
| 61 | CRT_ABHA_405 | Document Verification | Optional | NOT RUN | — |
| 62 | CRT_ABHA_406 | Document Upload | Optional | NOT RUN | — |
| 63 | CRT_ABHA_407 | Manual Verification and ABHA Creation | Optional | NOT RUN | — |
| 64 | CRT_ABHA_408 | Display of ABHA Number | Optional | NOT RUN | — |
| 65 | CRT_ABHA_410 | View and Download ABHA details. (If integrators is generating ABHA card) | Optional | NOT RUN | — |
| 66 | CRT_ABHA_411 | View and Download ABHA details. (If integrators is not generating ABHA card) | Optional | NOT RUN | — |
| 69 | VRFY_ABHA_101 | ABHA Number Verification using Aadhaar OTP | Mandatory | PARTIAL | 21 Sep ~11:38 UTC: login via Aadhaar OTP request 200, verify 409 `duplicate_abha`. ABDM accepted the OTP; bind refused on the second chart. Green linked banner not shown here (already bound to the first chart). |
| 70 | VRFY_ABHA_102 | ABHA Address Verification using Aadhaar OTP | Mandatory | NOT RUN | — |
| 72 | VRFY_ABHA_201 | ABHA Number verification using mobile OTP(ABHA Linked Mobile Number ) | Mandatory | PARTIAL | Re-run 21 Sep 2026: request-otp HTTP 200 at 10:46:19 UTC, participant-entered OTP, verify-otp HTTP 200 at 10:47:40 UTC, verified-and-linked UI on the existing chart. Full profile, edit restrictions, wrong OTP and resend checks remain. |
| 73 | VRFY_ABHA_202 | ABHA Address verification using mobile OTP(ABHA Linked Mobile Number ) | Mandatory | NOT RUN | — |
| 75 | VRFY_ABHA _301 | Fetch ABHA details using Mobile (communication)authentication . Multi authentication feature also need to be implemented like Captcha preferred | Mandatory | NOT RUN | — |
| 76 | VRFY_ABHA _302 | ABHA Details not exists to communicated Mobile Number | Mandatory | NOT RUN | — |
| 77 | VRFY_ABHA _303 | ABHA Details exists to communicated Mobile Number. | Mandatory | NOT RUN | — |
| 78 | VRFY_ABHA _304 | Incorrect OTP | Mandatory | NOT RUN | — |
| 79 | VRFY_ABHA _305 | Resend OTP Functionality | Mandatory | NOT RUN | — |
| 81 | VRFY_ABHA_401 | Fetch ABHA details using Aadhaar Number | Mandatory | PARTIAL | Same login-via-Aadhaar verify as 101: ABDM returned an identity (else persist would not reach the duplicate guard). Details were not shown on this chart because bind was refused. |
| 82 | VRFY_ABHA_402 | Incorrect OTP | Mandatory | NOT RUN | — |
| 83 | VRFY_ABHA_403 | ABHA Details not exists to Aadhaar Number | Mandatory | NOT RUN | — |
| 84 | VRFY_ABHA_404 | ABHA Details exists to Aadhaar Number | Mandatory | PARTIAL | Enrol OTP 400 `loginId` on Create ABHA, then login-via-Aadhaar OTP 200 + verify reaching `duplicate_abha`, show this Aadhaar already has an ABHA. |
| 85 | VRFY_ABHA_405 | Resend OTP Functionality | Mandatory | NOT RUN | — |
| 87 | VRFY_ABHA_501 | ABHA Number verification using Aadhaar Biometric - Fingerprint | Optional | GAP | No fingerprint/biometric verifier on the desk. |
| 88 | VRFY_ABHA_502 | ABHA Address verification using Aadhaar Biometric - Fingerprint | Optional | GAP | Same as 501. |
| 90 | VRFY_ABHA_501 | Reading ABHA Profile Info using ABHA QR Code | Optional | NOT RUN | — |
| 92 | PROF_ABHA_601 | Mobile Update | Optional | GAP | No ABHA profile-update APIs or desk/portal editors. |
| 93 | PROF_ABHA_602 | Photo Update | Optional | GAP | Same as 601. |
| 94 | PROF_ABHA_603 | Email Update | Optional | GAP | Same as 601. |
| 95 | PROF_ABHA_604 | Re-KYC | Optional | GAP | Same as 601. |
| 96 | PROF_ABHA_605 | Delete ABHA | Optional | GAP | Same as 601. |
| 98 | TAGGING_UNIQUEPATIENTID_UNIQUEABHANUMBER | Verify one ABHA Number is linked to the unique patient ID in HIMS | Mandatory | PARTIAL | Positive bind on first chart (mobile OTP). Duplicate bind on second chart refused (`409 duplicate_abha`). New-ABHA enrolment then bound a different ABHA onto the participant-approved new chart (`identity_status=verified`; chart identifier withheld). |
| 100 | SHARE _PATIENT_PROFILE_701 | Share Patient Profile | Mandatory | NOT RUN | — |

## M2

Source: [M2_BUILDING_HIP_WITH_APIS_UPDATED_22_Aug_871c2f7fcd.xlsx](../ABDM%20DOCS/M2_BUILDING_HIP_WITH_APIS_UPDATED_22_Aug_871c2f7fcd.xlsx), sheet **Building HIP**.

| Row | Case ID | Function / scenario | Source applicability label | Live result | Evidence |
|---|---|---|---|---|---|
| 12 | Health_RECORD_CREATION_101 | Creation of Health Records | Mandatory | NOT RUN | — |
| 15 | HIP_INTI_LINK_201 | Link record via mobile OTP | Optional | NOT RUN | — |
| 16 | HIP_INTI_LINK_202 | Receive OTP | Optional | NOT RUN | — |
| 17 | HIP_INTI_LINK_203 | OTP validation | Optional | NOT RUN | — |
| 18 | HIP_INTI_LINK_204 | Creation of new Token | Optional | NOT RUN | — |
| 19 | HIP_INTI_LINK_205 | Linking of Health Records | Optional | NOT RUN | — |
| 20 | HIP_INTI_LINK_206 | Pull Records | Optional | NOT RUN | — |
| 22 | HIP_INTI_LINK_301 | Link record via aadhaar linked mobile OTP | Optional | NOT RUN | — |
| 23 | HIP_INTI_LINK_302 | Receive OTP | Optional | NOT RUN | — |
| 24 | HIP_INTI_LINK_303 | OTP validation | Optional | NOT RUN | — |
| 25 | HIP_INTI_LINK_304 | Creation of new Token | Optional | NOT RUN | — |
| 26 | HIP_INTI_LINK_305 | Linking of Health Records | Optional | NOT RUN | — |
| 27 | HIP_INTI_LINK_306 | Pull Records | Optional | NOT RUN | — |
| 29 | HIP_INTI_LINK_401 | Direct Auth mode for Linking of Health Records | Optional | NOT RUN | — |
| 30 | HIP_INTI_LINK_402 | Notification on PHR App | Optional | NOT RUN | — |
| 31 | HIP_INTI_LINK_403 | Creation of Linking Token | Optional | NOT RUN | — |
| 32 | HIP_INTI_LINK_404 | Linking of Health Records | Optional | NOT RUN | — |
| 33 | HIP_INTI_LINK_405 | Pull Records | Optional | NOT RUN | — |
| 35 | HIP_INIT_GRANT_CONSENT_ | HIP must save consent (s)granted for a ABHA address in their system | Mandatory if the intergrator is implementing HIP initated linking using Direct Auth | NOT RUN | — |
| 37 | HIP_INIT_REVOKE_CONSENT | HIP must delete consents for a ABHA address in their system when it is revoked | Mandatory if the intergrator is implementing HIP initated linking using Direct Auth | NOT RUN | — |
| 39 | HIP_INIT_EXPIRE_CONSENT | HIP must delete consents for a ABHA address in their system when it is expired | Mandatory if the intergrator is implementing HIP initated linking using Direct Auth | NOT RUN | — |
| 41 | HIP_INTI_LINK_501 | Link record via Demographic Auth | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 42 | HIP_INTI_LINK_502 | Sharing demographic details | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 43 | HIP_INTI_LINK_503 | Validate the demographic details | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 44 | HIP_INTI_LINK_504 | Creation of Linking Token | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 45 | HIP_INTI_LINK_505 | Linking of Health Records | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 46 | HIP_INTI_LINK_506 | Pull Records | Mandatory for the Government Integartors / Private Integrators | NOT RUN | — |
| 48 | USER_INIT_LINK_601 | Login into PHR App | Not specified on this row; see source section | NOT RUN | — |
| 49 | USER_INIT_LINK_602 | Search for Facility/ HIP | Mandatory | NOT RUN | — |
| 50 | USER_INIT_LINK_603 | Share User Profile Details with Facility/ HIP | Mandatory | NOT RUN | — |
| 51 | USER_INIT_LINK_604 | Fetch Health Records | Mandatory | NOT RUN | — |
| 52 | USER_INIT_LINK_605 | Provide Consent for Health Record Linking | Mandatory | NOT RUN | — |
| 53 | USER_INIT_LINK_606 | Validate request | Mandatory | NOT RUN | — |
| 54 | USER_INIT_LINK_607 | Pull Records | Mandatory | NOT RUN | — |
| 56 | HIP_INIT_NOTIFY_HIECM | sending notification to the patient on their mobile with deep link | Mandatory | NOT RUN | — |
| 58 | HIP_INIT_SHARE_CARECONTEXT | HIP must share health records associated with care context on request | Mandatory | NOT RUN | — |

## M3

Source: [M3_BUILDING_HIU_WITH_APIS_UPDATED_22_August_de6a02460a.xlsx](../ABDM%20DOCS/M3_BUILDING_HIU_WITH_APIS_UPDATED_22_August_de6a02460a.xlsx), sheet **Building HIU**.

| Row | Case ID | Function / scenario | Source applicability label | Live result | Evidence |
|---|---|---|---|---|---|
| 8 | HIU_FLOW_101 | Patient Discovery | Mandatory | NOT RUN | — |
| 9 | HIU_FLOW_102 | Consent Request Initiation | Mandatory | NOT RUN | — |
| 10 | HIU_FLOW_103 | Notification to PHR | Mandatory | NOT RUN | — |
| 11 | HIU_FLOW_104 | Listing of Consent Requests | Mandatory | NOT RUN | — |
| 12 | HIU_FLOW_105 | Consent Request is Denied | Mandatory | NOT RUN | — |
| 13 | HIU_FLOW_106 | Consent Request is Approved | Any one of them is mandatory | NOT RUN | — |
| 14 | HIU_FLOW_107 | Fetch health data for (HI Type = DiagnostocReport Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 15 | HIU_FLOW_108 | Fetch health data for (HI Type = Prescription-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 16 | HIU_FLOW_109 | Fetch health data for (HI Type = DischargeSummary-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 17 | HIU_FLOW_110 | Fetch health data for (HI Type = CosultingNote-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 18 | HIU_FLOW_111 | Fetch health data for (HI Type = Immunization record-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 19 | HIU_FLOW_112 | Fetch health data for (HI Type = Health Record-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 20 | HIU_FLOW_113 | Fetch health data for (HI Type = Wellness Record-Structured/Un-Structured) | Not specified on this row; see source section | NOT RUN | — |
| 22 | HIU_FLOW_201 | Revoke Consent | Mandatory | NOT RUN | — |
| 23 | HIU_FLOW_202 | Revoke Consent | Mandatory | NOT RUN | — |
| 25 | HIU_FLOW_301 | Consent Expiry | Not specified on this row; see source section | NOT RUN | — |

## M1 product-path wiring — 21 September 2026

This section records which workbook rows have a HealthDoc product path, so a
live session with a consenting participant can be planned case by case. **It
changes no Live result above**; a product path is a prerequisite for a case,
not evidence of it. Contracts below are taken from the official
`Milestone_1_Postman_Collection_18_08_2025` (paths relative to the ABHA host
`/abha/api`).

| Rows | Product path | Added / status |
|---|---|---|
| CRT_ABHA_101/102/104/105/107 | Reception → Create ABHA → Aadhaar OTP (`/v3/enrollment/request/otp`, `/v3/enrollment/enrol/byAadhaar`) | Existing |
| CRT_ABHA_106, VRFY_ABHA_305/405 (Resend OTP) | “Resend OTP” in the OTP step: `POST /abdm/abha/enrol/aadhaar/resend-otp`, `POST /abdm/abha/login/resend-otp`. Server-enforced 30 s cooldown and 3 resends per desk attempt; the identifier is re-supplied by the desk and never stored; the previous session is consumed only after ABDM accepted the new request | **Added 21 Sep** (`feat/abdm-m1-desk-otp-resend-aadhaar-verify`) |
| VRFY_ABHA_304/402 (Incorrect OTP) | A gateway 4xx on the verify leg is now HTTP 400 `otp_rejected` (was 502 `abdm_rejected`); the session stays alive for a retry or resend; the desk shows the refusal and clears the code field | **Added 21 Sep** |
| VRFY_ABHA_101, VRFY_ABHA_401/403/404 (existing ABHA via Aadhaar OTP) | “OTP through Aadhaar” method on Use existing ABHA: `/v3/profile/login/request/otp` with scope `["abha-login","aadhaar-verify"]`, `loginHint` `aadhaar`, `otpSystem` `aadhaar`; verify leg quotes the same scope from the session | **Added 21 Sep** |
| VRFY_ABHA_201 | Use existing ABHA → OTP to ABHA-linked mobile | Existing (PARTIAL live) |
| TAGGING_UNIQUEPATIENTID_UNIQUEABHANUMBER | Binding on verification; `GET/DELETE /abdm/abha/patients/{id}/abha` | Existing (PARTIAL live) |
| SHARE_PATIENT_PROFILE_701 | Scan-and-Share desk (`scan_share_router.py`) | Existing |
| CRT_ABHA_108/109 (communication mobile) | Same enrolment session: `POST /abdm/abha/enrol/mobile/request-otp` then `verify-otp`. Wire matches the collection (`txnId`, scope `abha-enrol`+`mobile-verify`, encrypted mobile, `auth/byAbdm`). A refused OTP or upstream error leaves the previous stage. Several accounts are refused rather than taking the first. | **Code 21 Sep** (`feat/abdm-m1-enrol-consent-mobile-address`). Not a live case. |
| CRT_ABHA_112 (suggested ABHA address) | `GET /v3/enrollment/enrol/suggestion` with `Transaction_Id`, then `POST /enrol/abha-address` for the address the desk selected. Several suggestions are not preselected. A refusal keeps the session. | **Code 21 Sep**. Not a live case. |
| CRT_ABHA_113 (display ABHA number) | Shown on the verified panel | Existing |
| CRT_ABHA_114/115, CRT_ABHA_209/210/308/309 (view/download ABHA card) | Authorized proxy: `GET /abdm/abha/patients/{id}/abha-profile` and `abha-card`. The enrolment/login X-token stays encrypted in `abha_profile_token_encrypted` (migration 0083) and is not the HIP linking token. The desk labels this card as the NHA card, distinct from the hospital UHID card. | **Code 21 Sep**. Not a live download. |
| VRFY_ABHA_202 (ABHA address via mobile OTP) | **No product path** (`loginHint` `abha-address`) | Missing |
| VRFY_ABHA_301–303 (fetch by communication mobile, account selection) | **No product path.** `/v3/profile/login/request/otp` `{scope:["abha-login","mobile-verify"], loginHint:"mobile", …}` → `/v3/profile/login/verify` (may return several `accounts` and a `T-token`) → `POST /v3/profile/login/verify/user` header `T-token: Bearer …` body `{ABHANumber, txnId}`. The current verify leg deliberately refuses a multi-account result (`abdm_account_selection_required`) rather than guessing | Missing |
| CRT_ABHA_301–309 (demographic authentication) | **No product path**; not in the inspected collection folders used above — confirm the v3 route with NHA before building | Missing |
| CRT_ABHA_2xx (biometric), 4xx (document), PROF_ABHA_6xx, biometric/QR verification | Optional rows; no product path | Not planned |

Live execution of any row still needs a consenting participant entering
their own OTPs privately, the sandbox credentials configured on the running
stack, and case-by-case evidence recorded here with the revision.

### Live preflight — 21 September 2026, ~14:20 IST (read-only; no NHA call)

- **Callback ingress:** `abdm.healthdoc.world` resolves through Cloudflare; the
  local connector LaunchAgent `com.healthdoc.abdm-tunnel` is running. `/`
  returns 404 from the connector's ingress rule as designed, but the callback
  route returned **502**: the dev stack's nginx/backend containers had been
  stopped for ~28 hours, so any NHA (re)delivery in that period was refused at
  the edge. Between roughly 13:00 and 14:00 IST the isolated verification
  stack `healthdoc-cw` held port 443, so a callback in that hour would have
  reached a fresh database with no bridge state and its receipt was discarded
  with that stack. Neither window shows evidence of an actual NHA attempt.
- **Dev database:** alembic head **0079**; migrations 0080–0082 are not
  applied locally. Back up, then migrate before running the current code.
- **Receipts:** `abdm_callback_receipts` holds 5 rows on 14 September and 32
  on 18 September at 21:35:46 UTC — all 16 routes within 0.3 s answering
  400/422, i.e. a synthetic refusal sweep, not NHA traffic. **No genuine
  callback has arrived since the missing token callback was first reported.**
- **Jobs:** `context_notify` pending 22 (grew from 18 as documents were
  finalized), `link_context` pending 1 (3 attempts, 11 September — the
  expired link), `link_token` done 2 (12 September). Nothing was started,
  drained, regenerated or reset.

## Evidence needed for a live result

Record the source row, application commit, test time with timezone, local operator role, redacted request/correlation IDs, expected result, observed result, and any private evidence location. A queued operation or HTTP 202 is not completion: verify the callback, persisted state, correct patient's document and consumer-side rendering. Denial, revocation and expiry require a fresh refusal to fetch/display, not only a status-label change.
