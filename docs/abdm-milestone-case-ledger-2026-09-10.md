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

**30 September – 1 October: M2 HIP-initiated linking (demographic auth) and data transfer, live round trip.**
The participant's chart (identifier withheld) was linked to one finalized care context, the allowlisted
synthetic WellnessRecord, and the participant then pulled it in the ABHA PHR app, which displays it under
HealthDoc Facility (participant-confirmed, 1 October). All times UTC; no tokens, OTPs or clinical content recorded.

| Step | Correlation | Time | Result |
|---|---|---|---|
| `generate-token` (name, gender, year of birth) | REQUEST-ID `c7dc17db-48b5-51be-bbef-67caaf0460e7` | 30 Sep 17:37:18 | 202 |
| `on-generate-token` callback | receipt `e6ebed75` | 30 Sep 17:53:22 | link token received (callback ~16 min after request) |
| `link/carecontext` | REQUEST-ID `c9f734c6-a494-508a-ab18-176a22791b00` | 30 Sep 17:53:22 | 202 |
| `link/on_carecontext` | receipt `1eae59b3` | 30 Sep 17:53:23 | result received; refused locally for a zone-less TIMESTAMP (fixed in #611); link confirmed from the stored receipt by an audited operator reconciliation |
| PHR | — | 30 Sep | "New Record Added" notifications; record visible under HealthDoc Facility |
| `consent/request/hip/notify` (GRANTED) | REQUEST-ID `127b4f01-a4ea-49d9-b90d-29f94cf2a4e6`, artefact `74674494-f72b-4c8b-bcce-322f8f15f033` | 1 Oct 11:05:14 | 202, acknowledged |
| `hip/health-information/request` | REQUEST-ID `9076431b-5047-4a7c-985c-897c6a64d699`, transaction `428d7c38-76b2-4418-a936-8c26ea7a9aaf` | 1 Oct 11:05:18 | 202, acknowledged |
| encrypted push to the PHR `dataPushUrl` | same transaction | 1 Oct 11:05:18–22 | delivered, 1 entry |
| `health-information/notify` (TRANSFERRED, DELIVERED) | — | 1 Oct 11:05:22 | accepted |

Earlier attempts in the same run found six defects, each fixed with regression tests (#609–#613 merged to staging, #614 in review): link display
characters and length (#609, #610: NHA `ABDM-9999` "Invalid display"), zone-less callback TIMESTAMP and a consent
notice without `consentDetail.hiu` (#611), acknowledgements without REQUEST-ID and an empty care context in failure
notices (#612), the HIP push key encoding, checksum and status values (#613: the PHR requires the HIP key as X.509
SubjectPublicKeyInfo and an MD5 checksum), and a transfer stranded after its push retries ran out (#614). NHA
delivered several callbacks about 16 minutes after creating them; a PHR fetch whose consent notice arrived late
failed and needed retrying (raised with NHA support).

This is live sandbox evidence for the rows marked below, not NHA assessment or M2 certification.

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

## M1 sweep — 7 October 2026 (supersedes the M1 rows above where they overlap)

Facility DEV002 (HFR `IN2710005985`), reception desk `dev2.reception`, chart of the
consenting participant (identifiers withheld; ABHA address only shown on the
evidence screenshots, which stay out of the repository). Participant entered
every Aadhaar number and OTP; the operator never typed either. Times UTC, from
the backend access log. Screenshots: `abdm-evidence/M1/` beside the project,
named by case ID. Code: WIP commits `c11d4f21`, `6aa6d77f`, `2b05859f`
(PR pending).

| Case | Result | Time | Evidence / note |
|---|---|---|---|
| VRFY_ABHA_201 (ABHA number, linked-mobile OTP) | PASS | 08:04:52 request 200; 08:05:49 wrong OTP 400; 08:07:32 resend 200; 08:08:49 verify 200 | `VRFY_ABHA_201_*`. Wrong OTP now says ABDM did not accept the OTP (was 502 "temporarily unavailable" at 07:56; ABDM answers HTTP 200 `authResult: failed`). |
| CRT_ABHA_114/115 (NHA ABHA card) | PASS | 08:09:06 card 200 | `VRFY_ABHA_201_d_nha_card.png` (sandbox "Specimen Copy"). Contains participant photo/DOB/mobile: do not attach unredacted. |
| VRFY_ABHA_101 / 401 / 404 (Aadhaar OTP, ABHA exists) | PASS | 08:11:13 request 200; 08:12:44 verify 200 | `VRFY_ABHA_401_*`; verified and linked. |
| VRFY_ABHA_402 (incorrect OTP) | PASS | 08:11:57 400 | `VRFY_ABHA_402_wrong_otp.png` |
| VRFY_ABHA_405 (resend) | PASS | 08:12:14 200 | `VRFY_ABHA_405_resend.png` |
| VRFY_ABHA_301 / 303 (communication mobile + captcha, ABHA exists) | PASS | 08:14:18 request 200; 08:15:24 verify 200 | `VRFY_ABHA_301_*`, `VRFY_ABHA_303_verified.png`. Captcha solved by the participant. |
| VRFY_ABHA_304 (incorrect OTP) | PASS | 08:14:51 400 | `VRFY_ABHA_304_wrong_otp.png` |
| VRFY_ABHA_305 (resend) | PASS | 08:15:09 200 | `VRFY_ABHA_305_resend.png` |
| VRFY_ABHA_302 (no ABHA for the mobile) | PASS after fix | 09:29:11 ABDM 404 `ABDM-1115` (REQUEST-ID `2dcd6cfa-28d0-44bb-a22a-213497c14904`) → 502 "declined"; 09:32:19 same (`54393392-0b00-4e28-b31a-f7fc7f7431e6`) → **404 `abha_not_found_for_mobile`** | `VRFY_ABHA_302_*`. ABDM refuses the OTP request outright and sends no OTP; the desk now shows NHA's wording. Participant-supplied mobile with no ABHA. 09:27:43 attempt hit an ABDM session 500 (transient; three session probes then succeeded). |
| CRT_ABHA_102 / 103 (consent, Hindi) | PASS (display) | — | NHA declaration with English/हिन्दी toggle and both confirmations on the Create ABHA screen (`CRT_ABHA_104_0_start.png`). |
| CRT_ABHA_104 (invalid Aadhaar) | PASS after fix | 08:17:59 ABDM 422 `ABDM-1204` (REQUEST-ID `7eacbae3-b47b-482a-87e6-427dfcb3f0c0`) → 502; 08:29:10 ABDM 400 keyed `loginId` (`0e2b180c-537a-4d1c-aca1-e8327a6c7ed8`) → 502; 08:31:06 same (`3f5b4e4d-06a3-476d-94af-91931670233d`) → **400 `aadhaar_invalid`** | `CRT_ABHA_104_1_before_fix.png`, `CRT_ABHA_104_2_after_fix.png`. ABDM uses two refusal shapes for one mistake; both now map to "ABDM did not accept this Aadhaar number". |
| CRT_ABHA_105 / 106 (Aadhaar OTP sent, resend) | PASS | 08:33:52 request 200; 08:34:45 resend 200 | `CRT_ABHA_106_*`. OTP deliberately not entered: the Aadhaar already holds an ABHA. |
| CRT_ABHA_301–309 (demographic authentication) | DEFERRED | 08:37:43, 08:50:38 local 400 `abdm_demographic_not_enabled` | `CRT_ABHA_301_*`. NHA restricts `demo_auth` to approved government-programme integrations; needs the HidIntegratedProgram role and a registered `BENEFIT_NAME` (ABDM-1094 when absent). HealthDoc will register as government; request enablement when programme approval/tender is held. Screen previously showed a generic "check the highlighted fields"; now names the cause. |
| SHARE_PATIENT_PROFILE_701 (Scan & Share) | PASS on HealthDoc; token not returned to the app (sandbox delay) | QR scanned ~08:55; share delivered 09:12:30 (~17 min late), 202; ticket 2 bound to the chart; `on-share` 09:13:24 refused by ABDM `ABDM-1015` "Request Timed out"; desk check-in OPD1 09:23:16 | Counter QR `https://phrsbx.abdm.gov.in/share-profile?hip-id=IN2710005985&counter-id=OPD1`. `SHARE_701_0`–`_3`. The PHR app timed out ("taking longer than expected") because NHA delivered the share after its own reply window; HealthDoc replied within a minute of receipt (the session runner had stopped with the Docker restart and was restarted with its original cutoff). Full success on DEV001, 29 Sep 11:58:53, desk token 187. |

Other observations: 08:02:08 request-otp 503 (ABDM session endpoint, intermittent);
07:56 two verify 502s were the pre-fix wrong-OTP handling, not outages. Docker
Desktop stopped when the host disk filled (~08:21) and was restarted at 08:26;
the public callback GET returned 405 afterwards.

## M2

Source: [M2_BUILDING_HIP_WITH_APIS_UPDATED_22_Aug_871c2f7fcd.xlsx](../ABDM%20DOCS/M2_BUILDING_HIP_WITH_APIS_UPDATED_22_Aug_871c2f7fcd.xlsx), sheet **Building HIP**.

| Row | Case ID | Function / scenario | Source applicability label | Live result | Evidence |
|---|---|---|---|---|---|
| 12 | Health_RECORD_CREATION_101 | Creation of Health Records | Mandatory | PARTIAL | A finalized OP consultation was created through the consultation workflow (29 Sep). The record shared live was the allowlisted synthetic WellnessRecord, because the treating clinician has no registration number for transfer. |
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
| 41 | HIP_INTI_LINK_501 | Link record via Demographic Auth | Mandatory for the Government Integartors / Private Integrators | PASS (live, 30 Sep) | See the 30 Sep – 1 Oct entry above: token request `c7dc17db…`, link `c9f734c6…`, record visible in the PHR app. |
| 42 | HIP_INTI_LINK_502 | Sharing demographic details | Mandatory for the Government Integartors / Private Integrators | PASS (live, 30 Sep) | `generate-token` carried name, gender and year of birth (REQUEST-ID `c7dc17db…`), 202. |
| 43 | HIP_INTI_LINK_503 | Validate the demographic details | Mandatory for the Government Integartors / Private Integrators | PASS (live, 30 Sep) | NHA validated the demographics and issued a link token (callback receipt `e6ebed75`). |
| 44 | HIP_INTI_LINK_504 | Creation of Linking Token | Mandatory for the Government Integartors / Private Integrators | PASS (live, 30 Sep) | `on-generate-token` delivered the link token for request `c7dc17db…`. |
| 45 | HIP_INTI_LINK_505 | Linking of Health Records | Mandatory for the Government Integartors / Private Integrators | PASS (live, 30 Sep) | `link/carecontext` `c9f734c6…` 202; `link/on_carecontext` received; the PHR app shows the record under HealthDoc Facility. |
| 46 | HIP_INTI_LINK_506 | Pull Records | Mandatory for the Government Integartors / Private Integrators | PASS (live, 1 Oct) | PHR fetch → consent `74674494…` → request `9076431b…` → encrypted push delivered (transaction `428d7c38…`); participant confirmed the record renders. |
| 48 | USER_INIT_LINK_601 | Login into PHR App | Not specified on this row; see source section | NOT RUN | — |
| 49 | USER_INIT_LINK_602 | Search for Facility/ HIP | Mandatory | NOT RUN | — |
| 50 | USER_INIT_LINK_603 | Share User Profile Details with Facility/ HIP | Mandatory | NOT RUN | — |
| 51 | USER_INIT_LINK_604 | Fetch Health Records | Mandatory | NOT RUN | — |
| 52 | USER_INIT_LINK_605 | Provide Consent for Health Record Linking | Mandatory | NOT RUN | — |
| 53 | USER_INIT_LINK_606 | Validate request | Mandatory | NOT RUN | — |
| 54 | USER_INIT_LINK_607 | Pull Records | Mandatory | NOT RUN | — |
| 56 | HIP_INIT_NOTIFY_HIECM | sending notification to the patient on their mobile with deep link | Mandatory | NOT RUN | — |
| 58 | HIP_INIT_SHARE_CARECONTEXT | HIP must share health records associated with care context on request | Mandatory | PASS (live, 1 Oct) | Shared the linked care context on the PHR's request: delivered and reported TRANSFERRED/DELIVERED. Refusal and expiry cases not yet run. |

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

## M2 and M3 — 6–7 October 2026 (supersedes the NOT RUN rows above where they overlap)

Times UTC. Participants: the owner (`kandol007@sbx`), a second consenting
participant (`suprabhakumari1009@sbx`) and a third, Aryan Raj, registered with
his agreement for the SMS case (`rajaryan25200225@sbx`). Every consent was
granted, denied or revoked by the participant in the ABHA app. Screenshots:
`abdm-evidence/M2/` and `abdm-evidence/M3/` beside the project.

### M2

| Case | Result | Correlation / time | Evidence / note |
|---|---|---|---|
| Health_RECORD_CREATION_101 | PASS | 7 Oct 10:04:07 OPConsultation `encounter/b1c488d0-…` (dev2.doctor, DEV002); 6 Oct OPConsultation, Prescription, 2× DiagnosticReport, Invoice | Finalized through the consultation, lab and billing workflows. |
| HIP_INIT_NOTIFY_HIECM | PASS | Patient with mobile and no ABHA; `sms/notify2` accepted 10:04:09; SMS on the phone at 10:04 ("Your HealthDoc Sandbox Test Hospital reports are now ready … phrsbx.abdm.gov.in/phr/v3/uhi?hipId=IN2710005985") | `HIP_INIT_NOTIFY_HIECM_1_sms_received.png`. NHA's `sms/on-notify` acknowledgement never arrived (watched 25 min). |
| USER_INIT_LINK_601–606 | PASS | Discover 10:57:43 (on-discover 1 s); link init 10:57:47, HealthDoc OTP by MSG91, on-init accepted 10:57:48; confirm 11:00:46, link `confirmed` | `HIP_INIT_NOTIFY_HIECM_2_record_found.png`, `_3_linked_facility.png`. Matched on verified mobile, gender, birth year and name. A first link at 10:11:50 discovered the record but NHA never delivered its init. |
| USER_INIT_LINK_607 / HIP_INIT_SHARE_CARECONTEXT | PASS (participant 2); BLOCKED (participant 3) | 7 Oct 07:37:25–07:37:39 DEV002 delivered 5 bundles to the PHR (`90764936`); participant 3: consents 11:17/11:20/11:26, HI request 11:42:34 (~25 min after consent), ack refused 401 → no push | NHA delivered the PHR's HI request after closing it; HealthDoc correctly declines to push on an unacknowledged request. Same pattern 07:13:29 (`14528869`). |
| HIP_INIT_GRANT/REVOKE/EXPIRE_CONSENT | N/A | — | Apply only to HIP-initiated linking by Direct Auth; HealthDoc links by demographics (501–506). |

### M3 (HealthDoc as HIU)

| Case | Result | Correlation / time | Evidence |
|---|---|---|---|
| HIU_FLOW_101 / 102 | PASS | Patient found with verified ABHA address; request `8d1cf1af` 05:14 (DEV002 ← DEV001) | `HIU_FLOW_101_102_patient_and_request_form.png` |
| HIU_FLOW_103 / 104 | PASS | Requests listed in the PHR with status | `HIU_FLOW_103_104_phr_consent_list.png` |
| HIU_FLOW_105 (denied) | PASS | `af25f1d7` 06:05 → denied 06:21 | `HIU_FLOW_105_phr_denied.png`, `HIU_FLOW_105_denied_and_201_revoked_7of7.png` |
| HIU_FLOW_106 (approved) | PASS | `8d1cf1af` granted 05:15; `7c4da967` (DEV001 ← DEV002) granted 07:43 | `HIU_FLOW_106_approved_received_5of5.png` |
| HIU_FLOW_107 / 108 / 110 / 111 / 113 (+ Invoice) | PASS | DEV002 received 7/7 05:52:57–05:53:11 (DiagnosticReport ×2, Prescription, OPConsultation, ImmunizationRecord, WellnessRecord, Invoice); DEV001 received 5/5 07:43:49–07:43:59 | `HIU_FLOW_107_diagnosticreport_viewed.png`, `_108_prescription_viewed.png`, `_110_opconsultation_viewed.png` (decrypted, NRCeS profiles) |
| HIU_FLOW_109 / 112 | NOT RUN | No DischargeSummary or HealthDocumentRecord in the source facility's finalized records | — |
| HIU_FLOW_201 / 202 (revoke) | PASS | `8d1cf1af` revoked 06:26; fetch, view and share refused afterwards | `HIU_FLOW_201_202_phr_revoked.png`; every View/Request control disabled |
| HIU_FLOW_301 (expiry) | PASS | `19356a77` WellnessRecord granted 06:51, 1/1 received 06:52:54, expired 07:25 | `HIU_FLOW_301_phr_expired.png`, `HIU_FLOW_301_consent_expired.png` |

Operator error, not a case: `0670e88f` (DEV001) asked for records up to a
future time and NHA refused it (`ABDM-9999`); resent correctly as `7c4da967`.
HealthDoc should refuse a future "to" date before sending (follow-up).

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
| VRFY_ABHA_202 (ABHA address via mobile OTP) | Use existing ABHA → ABHA address. OTP scope `abha-login` + `mobile-verify`. | **Code added** on `feat/abdm-m1-address-mobile-login`. Not a live case. |
| VRFY_ABHA_301–303 (fetch by communication mobile, account selection) | Communication mobile OTP. Several accounts are shown and the desk must choose. `POST /v3/profile/login/verify/user` uses the server-held `T-token`. A number outside that list is refused. | **Code added**. Not a live case. |
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
