# NHA functional testing and WASA certification — test plan

Date: 10 October 2026. Branch base: staging `dbb18f47`.
Owner request: check every functional test the NHA-empanelled agency will
perform and the WASA (CERT-In "Safe to Host") security tests, and plan to
perform them before the external auditors do.

This is a plan and a status map, not a pass claim. "Evidence" below means a
screenshot set in `abdm-evidence/` (outside the repository: it holds sandbox
participant screens) or a dated row in
`docs/abdm-milestone-case-ledger-2026-09-10.md`. A case passes NHA only when
NHA's tester sees it work.

## 1. What the external testers use

### NHA functional testing

NHA's sandbox page *Documentation → Test Cases*
(`sandbox.abdm.gov.in/sandbox/v3/new-documentation?doc=TestCases`) links:

| Workbook | Cases | Applies to HealthDoc |
|---|---|---|
| M1 ABHA creation and verification (V1_1) | 59 | Yes |
| M2 Building HIP (22 Aug) | 36 | Yes |
| M3 Building HIU (22 Aug) | 16 | Yes |
| M4 HFR, HPR | not yet read | Yes: "integrators are required to integrate the native HFR / HPR flow". `hfr/router.py`, `hfr/hpr_router.py` exist |
| PHR and Locker V3 | — | No: HealthDoc is not a PHR app |

The M1/M2/M3 files on NHA's page are byte-identical (same size) to the copies
in the owner's Downloads used here. The case ledger was built from the newer
M1 **V1_2** (7 Aug) copy; NHA's page still links **V1_1**. Ask NHA which the
tester will use (§6).

**Integrator category decides the mandatory set.** Several rows read
"Mandatory for Government", "either 114 or 115 mandatory for Government",
"HIP_INTI_LINK_5xx mandatory for Government integrators". HealthDoc will be
run under state-government rules, so this plan assumes the **Government**
column; confirm it with NHA.

### WASA (CERT-In empanelled auditor)

There is no single public CERT-In checklist. Issued Safe to Host certificates
for government sites state the audit was "as per OWASP web application
security standard and for known web application vulnerabilities"; some also
cite CERT-In Directions under section 70B of the IT Act, SANS Top 25, CWE/CVE
and WCAG. Certificates lapse **when the application changes or after one year**,
and are often issued on a staging URL with a condition to deploy on valid TLS
with server and OS hardening. Plan against:

- OWASP Top 10 (2021) and OWASP API Security Top 10 (2023), on both addresses
  (hospital and control room), every role, and the public pages;
- CERT-In Directions (28 April 2022): incident reporting within 6 hours,
  ICT logs kept for 180 days in India, clocks synced to NIC/NPL NTP
  (confirm wording against the official text before relying on it);
- dependency and image CVEs; TLS configuration; server hardening.

## 2. NHA mandatory cases — where HealthDoc stands

Legend: **Evidence** = live sandbox run captured; **Built** = code exists,
needs a captured run; **Blocked** = cannot run until the named item exists;
**Rerun** = captured once with a defect or partial result.

### M1 — ABHA creation and verification

| Case | Scenario | Status |
|---|---|---|
| CRT_ABHA_101 | Create ABHA option (Aadhaar OTP) | Evidence (21 Sep) |
| CRT_ABHA_102 / 302 | ABDM consent language, patient agrees | Built (`/enrol/consent`); capture |
| CRT_ABHA_104 / 304 | Aadhaar entry, invalid-number error | Evidence |
| CRT_ABHA_105, 107 | Aadhaar OTP entry and verification | Evidence (21 Sep) |
| CRT_ABHA_106 | Resend OTP, max 2, after 60 s | Evidence |
| CRT_ABHA_109 | Communication mobile ≠ Aadhaar mobile → OTP | Built (`/enrol/mobile/*`); capture |
| CRT_ABHA_112 | Pick ABHA address from ≥ 3 suggestions | Evidence (new participant, consented) |
| CRT_ABHA_113 / 307 | ABHA number displayed | Evidence for 113; capture 307 |
| CRT_ABHA_114 or 115 (and 308/309) | View / download ABHA card (one is mandatory for Government) | Built (`/patients/{id}/abha-card`, `/abha-profile`); capture |
| CRT_ABHA_301, 305, 306 | Demographic (offline) creation, profile completion | 301 evidence; 305/306 built (`/enrol/demographic`, LGD states/districts); capture |
| VRFY_ABHA_101 | ABHA number via Aadhaar OTP | Rerun on a chart not already linked (last run: OTP accepted, bind refused as duplicate) |
| VRFY_ABHA_102, 202 | ABHA address via Aadhaar OTP / mobile OTP | Evidence |
| VRFY_ABHA_201 | ABHA number via mobile OTP | Evidence |
| VRFY_ABHA_401, 402, 405 | Fetch by Aadhaar number, wrong OTP, resend | Evidence |
| VRFY_ABHA_403, 404 | Aadhaar with no ABHA / with ABHA | Capture (needs an Aadhaar without ABHA for 403) |

Optional M1 rows (biometric, DL/PAN, QR scan, profile updates, re-KYC,
delete) are not required; DL enrolment is built if NHA asks.

### M2 — HIP

| Case | Scenario | Status |
|---|---|---|
| Health_RECORD_CREATION_101 | Digital health records created | Evidence (finalized documents, six HI types) |
| HIP_INTI_LINK_501–506 | HIP-initiated linking by demographic auth (mandatory for Government) | **Evidence: live round trip 30 Sep – 1 Oct**, record pulled in the ABHA PHR app |
| HIP_INIT_NOTIFY_HIECM | Deep-link SMS notification when no ABHA address | Evidence |
| HIP_INIT_SHARE_CARECONTEXT | Share records on consent (encrypted push) | Evidence (1 Oct; both HI types under one consent after fix) |
| USER_INIT_LINK_602–607 | Patient finds HealthDoc in the PHR app, links with OTP, pulls records | **Blocked**: the mediated OTP must reach the patient by SMS. `ABDM_LINK_OTP_DELIVERY_URL` is unset; no SMS provider is contracted |
| HIP_INIT_GRANT/REVOKE/EXPIRE_CONSENT | Only if Direct Auth linking is offered | Not applicable unless Direct Auth is enabled |

### M3 — HIU

| Case | Scenario | Status |
|---|---|---|
| HIU_FLOW_101 | Find patient by ABHA number / address | Evidence |
| HIU_FLOW_102, 103 | Raise consent request; it appears in the PHR | Evidence for 103; capture the request form for 102 |
| HIU_FLOW_104 | List of consent requests (ABHA, purpose, status, dates) | Built; capture |
| HIU_FLOW_105 | Denied consent fetches nothing | Evidence |
| HIU_FLOW_106–113 | Approved consent, data viewed per HI type ("any one" mandatory) | Evidence for 106–110, 112; 111 Immunization and 113 Wellness to capture (NHA's November 2025 FAQ asks HMIS for eight types — §6) |
| HIU_FLOW_201 | Patient revokes in the PHR | Evidence |
| HIU_FLOW_202 | HIU can no longer view after revoke | Capture (HIU screen after the revoke) |
| HIU_FLOW_301 | Expired consent shows nothing | Evidence |

### M4 — HFR / HPR

Not assessed yet. The HFR (30 KB) and HPR (23 KB) workbooks are on NHA's
content server and are not in Downloads; download them, map them like the
tables above, and run them against `hfr/router.py` and `hfr/hpr_router.py`.

**Summary:** of the mandatory M1–M3 cases, the only one that cannot run
today is patient-initiated linking (SMS provider). Everything else is either
captured or built and needs one recorded run.

## 3. WASA — where HealthDoc stands

Existing evidence: authenticated OWASP ZAP API scan, 24 August 2026 (292
OpenAPI URLs, 0 High/Critical after the P0/P1 fixes), MFA/TOTP forced in
production, password policy, CSP nonce, audience check, role-boundary and
facility-scope tests, dependency audits. **That scan predates the control room,
public availability page, appointment requests, MCH and the control-room host;
the API has grown from 266 to about 413 routes. It must be rerun.**

Found while preparing this plan (fix before engaging the auditor):

| # | Finding | Why an auditor flags it | Fix |
|---|---|---|---|
| W1 | Hospital nginx proxies all of `/auth/` to Keycloak, so `/auth/admin/` (admin console) and `/auth/realms/master/` are reachable on the public hospital address. Confirmed on the local stack (both 200); the production `location /auth/` block has no exclusion either | OWASP A05/A01: administrative interface exposed to the internet | Return 404 for `/auth/admin/` and `/auth/realms/master/` on the public host; administer Keycloak over the private network or a VPN only |
| W2 | `/public/availability` and the portal appointment request ride the general API limit (30 r/s), with no captcha on the request form | A04 / API4: unrestricted resource consumption, form abuse | A separate, lower `limit_req` zone for public and portal-write routes; captcha (one already exists for ABHA) on the request form |
| W3 | No log rotation or retention policy in production Compose (only Prometheus 15 d); NTP source not documented | CERT-In Directions: 180 days of logs in India, NIC/NPL time sync | `logging:` rotation per service plus shipping to a store kept 180 days; document chrony to `samay1.nic.in` / NPL on both hosts |
| W4 | Keycloak pages carry a CSP with `'unsafe-inline'` | A05; auditors list it even when the theme needs it | Remove if the HealthDoc theme allows; otherwise record the justification in the audit scope document |
| W5 | Uploaded files have a `scan_status` column, but no malware scanner is deployed | A08 / file upload: auditors upload EICAR | Confirm what sets `scan_status`; add a scanner (ClamAV) or document the compensating control |

## 4. How we perform them

### Phase 0 — decisions and inputs (owner, before testing)

1. Confirm with NHA: integrator category (Government), which M1 workbook
   version the tester uses (V1_1 or V1_2), and the required HI types (FAQ's
   eight vs the M3 workbook's "any one").
2. Choose an SMS provider for the link OTP relay (for a state deployment,
   typically the state's NIC/CDAC SMS gateway) so USER_INIT_LINK can run.
3. Allow downloading the M4 HFR/HPR workbooks (30 KB and 23 KB).
4. Provide a stable staging environment with public HTTPS on both addresses
   for the external testers; certificates are tied to the audited version.

### Phase 1 — close the gaps (engineering)

- W1–W5 above, each as a PR with a regression test (W1 also in the nginx
  routing test).
- OTP relay integration with the chosen SMS provider.
- M4: map and run the HFR/HPR cases; fix what they expose.

### Phase 2 — internal NHA dry run (owner + engineering)

Every mandatory row in §2 run once on staging, by case ID, in workbook order:
the owner enters Aadhaar numbers and OTPs and approves or denies in the PHR
app; engineering runs the screens and records request IDs. Evidence goes to
`abdm-evidence/<M>/<CASE_ID>_*.png`, and the case ledger gets one row per
run (date, build, result). Negative cases (wrong OTP, denied, revoked,
expired, Aadhaar without ABHA) are run as deliberately as the happy paths.
Exit: every mandatory row has evidence on the build being submitted.

### Phase 3 — internal WASA pre-audit (engineering)

| Area | Tooling / method |
|---|---|
| Whole API, every role | Authenticated ZAP API scan (`scripts/security/run_zap_api_scan.sh`) against both hosts; target 0 High/Critical, every Medium explained |
| Access control | Role × route matrix (`tests/test_role_boundaries.py`) extended to the new modules; two-account and two-facility ID swaps on every ID route; control-room scope (district vs state); patient-portal binding |
| Injection, XSS, CSV/formula, path traversal, SSRF | ZAP active rules plus manual payloads on search, exports, uploads and every outbound URL setting |
| Authentication and session | TOTP enforced, brute-force lockout, password reset, logout and token revocation, session timeout, OTP throttling on ABHA flows |
| TLS and headers | testssl.sh on both public addresses and the private link (#690); HSTS, CSP, frame, referrer, cookies |
| Components | pip-audit, npm audit, trivy on every image, gitleaks over history |
| Uploads | EICAR, oversize, wrong type, polyglot files |
| Operations | Log retention and NTP (W3), backup and restore drill, incident-reporting runbook (6-hour CERT-In clock) |

Output: an audit scope document for the auditor (URLs, roles and test
accounts, API inventory, known limitations with justification) and a report of
what was found and fixed. Exit: no open High/Medium.

### Phase 4 — external

1. Submit for NHA functional testing; the empanelled agency runs the
   workbooks; fix and rerun any failed row.
2. Engage a CERT-In empanelled auditor on the frozen staging build; fix,
   get the retest, receive the Safe to Host certificate.
3. Any code change after the certificate means a re-audit of what changed;
   the certificate also expires after a year.

## 5. Who does what

| Owner | Engineering |
|---|---|
| NHA confirmations, SMS provider, auditor selection and contract, participant Aadhaar/OTP entry and PHR approvals, NHA portal submissions | Gap fixes (W1–W5, OTP relay, M4), dry-run screens and ledger, scans and manual security testing, audit scope document, remediation |

## 6. Open questions for NHA

1. Integrator category: Government (state deployment)?
2. M1 workbook version the tester uses: V1_1 (on the page) or V1_2?
3. HI types required for an HMIS: eight (November 2025 FAQ) or "any one" (M3 workbook)?
4. Is patient-initiated linking (USER_INIT_LINK) mandatory for us if HIP-initiated demographic linking passes?
