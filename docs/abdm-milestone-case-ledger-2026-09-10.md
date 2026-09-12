# ABDM M1–M3 supplied test-case execution ledger

Date: 10 September 2026. Initial baseline: `main` at `23c89e0`.
Live OTP fix: `fix/abdm-otp-live-verification`, based on `658e791`.

Status: live acceptance NOT COMPLETE. See [preflight evidence and blockers](abdm-live-preflight-2026-09-10.md).

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

All live statuses started as **NOT RUN**. Two now have **PARTIAL** evidence from the successful existing-number mobile-OTP browser flow and saved binding; neither is a complete workbook case. Gateway probes, unit tests and the user's report of PHR registration are not substitutes for end-to-end cases. Do not change a status without case-specific evidence. Never put ABHA/Aadhaar numbers, OTPs, tokens, private keys or identifiable clinical screenshots in this file.

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
| 22 | CRT_ABHA_101 | Create ABHA Option | Mandatory | NOT RUN | — |
| 23 | CRT_ABHA_102 | Consent collection | Mandatory | NOT RUN | — |
| 24 | CRT_ABHA_103 | Suggestions:- Consent collection should be multilingual | Optional | NOT RUN | — |
| 25 | CRT_ABHA_104 | Aadhaar collection and Error Message | Mandatory | NOT RUN | — |
| 26 | CRT_ABHA_105 | Aadhaar OTP Collection | Mandatory | NOT RUN | — |
| 27 | CRT_ABHA_106 | Resend OTP | Mandatory | NOT RUN | — |
| 28 | CRT_ABHA_107 | OTP based Aadhaar Authentication | Mandatory | NOT RUN | — |
| 29 | CRT_ABHA_108 | Communication Mobile Number verification-I | Optional | NOT RUN | — |
| 30 | CRT_ABHA_109 | Communication Mobile Number verification-II | Mandatory | NOT RUN | — |
| 31 | CRT_ABHA_112 | Suggested ABHA Address | Mandatory for Private /Government (Optional for integrated program using demo auth as they have default ABHA address generated) | NOT RUN | — |
| 32 | CRT_ABHA_113 | Display of ABHA Number | Mandatory | NOT RUN | — |
| 33 | CRT_ABHA_114 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | NOT RUN | — |
| 34 | CRT_ABHA_115 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_114 or CRT_ABHA_115 is mandatory for Governement Optional for Private | NOT RUN | — |
| 36 | CRT_ABHA_201 | Create ABHA Option | Optional | NOT RUN | — |
| 37 | CRT_ABHA_202 | Consent collection | Optional | NOT RUN | — |
| 38 | CRT_ABHA_203 | Suggestions:- Consent collection should be multilingual | Optional | NOT RUN | — |
| 39 | CRT_ABHA_204 | Aadhaar collection and Error Message | Optional | NOT RUN | — |
| 40 | CRT_ABHA_205 | Biometric based Aadhaar Authentication | Optional | NOT RUN | — |
| 41 | CRT_ABHA_206 | Communication Mobile Number verification-I | Optional | NOT RUN | — |
| 42 | CRT_ABHA_207 | Communication Mobile Number verification-II | Optional | NOT RUN | — |
| 43 | CRT_ABHA_208 | Display of ABHA Number | Optional | NOT RUN | — |
| 44 | CRT_ABHA_209 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | NOT RUN | — |
| 45 | CRT_ABHA_210 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_209 or CRT_ABHA_210 is mandatory for Governement Optional for Private | NOT RUN | — |
| 47 | CRT_ABHA_301 | Create ABHA Option | Mandatory | NOT RUN | — |
| 48 | CRT_ABHA_302 | Consent collection | Mandatory | NOT RUN | — |
| 49 | CRT_ABHA_303 | Suggestions:- Consent collection should be multilingual | Optional | NOT RUN | — |
| 50 | CRT_ABHA_304 | Aadhaar collection and Error Message | Mandatory | NOT RUN | — |
| 51 | CRT_ABHA_305 | Demographic Information based authentication | Mandatory | NOT RUN | — |
| 52 | CRT_ABHA_306 | Profile Completion | Mandatory | NOT RUN | — |
| 53 | CRT_ABHA_307 | Display of ABHA Number | Mandatory | NOT RUN | — |
| 54 | CRT_ABHA_308 | View and Download ABHA details. (If integrators is generating ABHA card) | Mandatory for Private | NOT RUN | — |
| 55 | CRT_ABHA_309 | View and Download ABHA details. (If integrators is not generating ABHA card) | Either of the test cases CRT_ABHA_308 or CRT_ABHA_309 is mandatory for Governement Optional for Private | NOT RUN | — |
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
| 69 | VRFY_ABHA_101 | ABHA Number Verification using Aadhaar OTP | Mandatory | NOT RUN | — |
| 70 | VRFY_ABHA_102 | ABHA Address Verification using Aadhaar OTP | Mandatory | NOT RUN | — |
| 72 | VRFY_ABHA_201 | ABHA Number verification using mobile OTP(ABHA Linked Mobile Number ) | Mandatory | PARTIAL | Browser request/verify HTTP 200; participant submitted OTP; verified-and-linked UI. Full profile, edit restrictions, wrong OTP and resend checks remain. See live preflight. |
| 73 | VRFY_ABHA_202 | ABHA Address verification using mobile OTP(ABHA Linked Mobile Number ) | Mandatory | NOT RUN | — |
| 75 | VRFY_ABHA _301 | Fetch ABHA details using Mobile (communication)authentication . Multi authentication feature also need to be implemented like Captcha preferred | Mandatory | NOT RUN | — |
| 76 | VRFY_ABHA _302 | ABHA Details not exists to communicated Mobile Number | Mandatory | NOT RUN | — |
| 77 | VRFY_ABHA _303 | ABHA Details exists to communicated Mobile Number. | Mandatory | NOT RUN | — |
| 78 | VRFY_ABHA _304 | Incorrect OTP | Mandatory | NOT RUN | — |
| 79 | VRFY_ABHA _305 | Resend OTP Functionality | Mandatory | NOT RUN | — |
| 81 | VRFY_ABHA_401 | Fetch ABHA details using Aadhaar Number | Mandatory | NOT RUN | — |
| 82 | VRFY_ABHA_402 | Incorrect OTP | Mandatory | NOT RUN | — |
| 83 | VRFY_ABHA_403 | ABHA Details not exists to Aadhaar Number | Mandatory | NOT RUN | — |
| 84 | VRFY_ABHA_404 | ABHA Details exists to Aadhaar Number | Mandatory | NOT RUN | — |
| 85 | VRFY_ABHA_405 | Resend OTP Functionality | Mandatory | NOT RUN | — |
| 87 | VRFY_ABHA_501 | ABHA Number verification using Aadhaar Biometric - Fingerprint | Optional | NOT RUN | — |
| 88 | VRFY_ABHA_502 | ABHA Address verification using Aadhaar Biometric - Fingerprint | Optional | NOT RUN | — |
| 90 | VRFY_ABHA_501 | Reading ABHA Profile Info using ABHA QR Code | Optional | NOT RUN | — |
| 92 | PROF_ABHA_601 | Mobile Update | Optional | NOT RUN | — |
| 93 | PROF_ABHA_602 | Photo Update | Optional | NOT RUN | — |
| 94 | PROF_ABHA_603 | Email Update | Optional | NOT RUN | — |
| 95 | PROF_ABHA_604 | Re-KYC | Optional | NOT RUN | — |
| 96 | PROF_ABHA_605 | Delete ABHA | Optional | NOT RUN | — |
| 98 | TAGGING_UNIQUEPATIENTID_UNIQUEABHANUMBER | Verify one ABHA Number is linked to the unique patient ID in HIMS | Mandatory | PARTIAL | Existing-ABHA positive binding persisted; one active matching identity in facility. Duplicate-refusal and new-ABHA branch not proven live. |
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

## Evidence needed for a live result

Record the source row, application commit, test time with timezone, local operator role, redacted request/correlation IDs, expected result, observed result, and any private evidence location. A queued operation or HTTP 202 is not completion: verify the callback, persisted state, correct patient's document and consumer-side rendering. Denial, revocation and expiry require a fresh refusal to fetch/display, not only a status-label change.
