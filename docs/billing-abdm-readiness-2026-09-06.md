# Billing review and ABDM M1–M3 runbook

Reviewed **6–7 September 2026**. Target day: **Monday, 7 September 2026 (IST)** —
now **today**, not a rolling "tomorrow" deadline.
Branch: `fix/billing-abdm-readiness`, based on `304cd02` from
`feat/billing-authority-and-nursing-handover`. Publication target: a feature PR
into staging; no production promotion is included.

## Decision

**Do not present M1, M2 and M3 as completed or certified on 7 September.**
The implementation has substantial protocol code, but no demonstrated sandbox
clinical round trip. The local development database has **zero** care contexts,
links, HIP requests, HIU consent requests, HIU requests and received bundles.
This is evidence about this database, not proof that nobody tested elsewhere.

An operator-led sandbox demonstration on 7 September is conditional on the prerequisites
below. Certification/production approval is a separate external process: NHA
requires a demonstration, functional testing/security assessment and exit
documentation. It is not granted by green unit tests or a successful session
request. [NHA integration and sandbox-exit FAQ](https://abdm.gov.in/FAQ).

## What this review fixed

| Defect | Fix and evidence |
|---|---|
| Billing payment/refund sent `{amount, currency}` as `amount`; server expects a decimal string | Both request adapters send `amount.amount`. Reproduced a real browser payment HTTP 422, added a failing adapter regression, then repeated the browser journey successfully. |
| Draft controls let staff change browser-only totals which would never persist | Financial edits are read-only. Added a real **Build charges** action, refreshed server totals/row version and displayed skipped/unpriced charge counts. No manual tariff/discount authority was invented. |
| Billing role was shown admin-only refund approval | Only admin sees Reverse. Browser test also proves billing's direct refund request gets 403. |
| Search only examined the first 20 invoices, with no page controls | Facility-scoped server search, matching count, stable ordering and Previous/Next. Query/status changes reset the page; stale list responses are ignored. PG regression failed with 132 matches instead of 1 before the fix. |
| M1 encryption used PKCS#1 v1.5 | Changed to OAEP with SHA-1 and MGF1/SHA-1, as explicitly published by the live ABHA certificate endpoint. The previous decrypt tests used the same wrong padding as the implementation. Corrected tests failed before the fix. |
| M1 login parsed an enrolment response | Parses `authResult` and exactly one active `accounts[]` entry. Failed/ambiguous/inactive results are refused without consuming the session. |
| Enrolment's `phrAddress[]` was passed to a scalar database field | Uses a declared preferred address or a single returned address. Multiple addresses without a preference are left unset, not guessed. Composes the name from returned name parts. |
| Enrolment UI sent `+91` mobile to a ten-digit-only backend field, then the backend RSA-encrypted it | Normalize at the ABHA API boundary only; send the mobile as ten national digits, as in the supplied successful M1 example. Aadhaar/login ID and OTP remain encrypted. Omit the invented null timestamp. Frontend and backend regressions failed before the fixes. |
| HIU accepted six purposes but always asked ABDM for care management | Restrict the public request schema to the implemented `CAREMGT` purpose and pass its mapping explicitly. Five previously accepted unmapped purposes now fail validation before a row or outbound request is created. Broader purpose support is not claimed. |
| Keycloak's cookie-probe iframe still exhausted the credential bucket after theme assets were exempted | Real production-preview logins captured HTTP 503 for `3p-cookies/step2.html` and later token requests. Exempt only GET/HEAD of the exact `step1.html`/`step2.html` pages. Login/token endpoints retain 10 requests/second and burst 20. All 19 proxy-policy tests and `nginx -t` pass. |

The existing billing policy remains: billing/admin operate the desk; pharmacy
may settle medicine-only invoices; reception/supervisor cannot bill; admin
approves refunds and the server retains its maker–checker restriction.

## Verification ledger

- Full PostgreSQL suite after all backend/proxy fixes: **1,299 passed**. Four
  pre-existing Pydantic alias warnings remain; do not describe this as warning-free.
  Two existing alert tests failed overnight because host-local dates were mixed
  with UTC events. Fixed test timestamps and added four UTC day-boundary cases;
  no alert-policy change. Final gate also confirms the **67-migration** linear
  chain at head `0060` and no schema PR-check blockers/warnings.
- Frontend: **26 tests passed**, typecheck passed and ESLint passed.
- Script tests: **14 passed**, including three safe collection-inventory tests.
- Additional production-preview checks: **9/9 real-login/access/keyboard/Axe
  gates** passed (including billing); no serious/critical Axe findings in those
  tested states. Silent SSO helper returned 200. **4/4 synthetic print-CSS
  smoke cases** produced PDFs. This is not every modal's accessibility or a
  clinical receipt/prescription content-and-print sign-off. Navigation/teardown
  produced aborted prefetch/iframe requests, not failing gate outcomes.
- Contract check: **196 frontend calls match OpenAPI**. Path existence does not
  prove payload or authorization correctness; the payment bug demonstrated that.
- Dependency audit: **0 known vulnerabilities** in the backend/frontend checks.
- Changed ABDM/script Python files pass Ruff. Billing's existing Python lint
  debt remains: 50 findings in its router (same count/codes at base commit) and
  an existing unused test import. This review did not rewrite those route
  signatures or claim whole-repository Python lint is clean.
- Real Keycloak browser billing workflow: **passed**. Reception creates a
  synthetic day-care visit; billing searches, builds, issues and collects ₹1.25;
  admin independently refunds ₹0.25; forbidden reception/billing/pharmacy
  operations are refused. Test records are retained in the local dev database.
- Development dashboard sweep on 7 September: **48/48 passed**, recovery off.
  The subsequent full workflow run passed **8/10 workflows**; nursing login and
  OPD consultation stalled. Next's log records a **memory-threshold restart**
  and nginx records upstream connection refusals during this interval; no rate
  limiting was recorded. The doctor loading-screen stall is not independently
  proven to share that cause. This run is **not** a complete release sign-off.
  The first production-preview run also passed **48/48 screens**, but only
  **7/10 workflows**: inventory, identity merge and OPD failed on actual Keycloak
  HTTP 503 rate-limit responses. That separate cause led to the exact cookie-probe
  exemption above, not a higher credential limit.
- **Final production-preview run `billing-abdm-final-20260907`: PASS.**
  **48/48 dashboards**, **10/10 workflows / 43 captured steps**, plus the
  separate superadmin platform/API/UI isolation gate (**1 captured step**).
  All three manifests share the run ID and pass `run_errors` / `run_warnings`
  from the existing evidence validator: no missing outcomes, no failures and
  no warnings. Recovery stayed disabled. Proxy/runtime logs for the final run
  show **zero** rate-limit refusals, connection refusals or memory restarts.
  Evidence: `docs/evidence/billing-abdm-final-2026-09-07/` (**92 referenced
  screenshots**). This proves the enumerated paths, not every possible action.
- Evidence is separate from the older role report:
  `docs/evidence/billing-abdm-2026-09-06/`. The workflow manifest is deliberately
  marked `fullRun: false` because this run selected billing only. Do not feed it
  to the whole-project evidence generator as a complete workflow run.
- No real Aadhaar/OTP was submitted, no consent was requested from a person, no
  external health record was transferred, and no tunnel/bridge settings changed.

The first 6 September development sweep also failed one eMAR screen while nginx
recorded 11 refused static-asset requests. A strict isolated nurse rerun passed
4/4; neither that targeted run nor a successful screenshot erases the failed run.
Workflow diagnostics now capture failed request paths/statuses and browser
errors, including failures before the first action. They exclude query strings,
headers and payloads.

The final nursing workflow includes admission, decimal/optional-field vitals,
SBAR handover to a named colleague, and discharge. OPD includes HOD roster,
reception visit/token/consent, doctor consultation and completion, lab sample/
preliminary result/self-verification refusal, and radiology schedule/reschedule/
scan/report/sign-off/history. Independent lab release still requires a second
technician; its absence is not hidden by the successful preliminary-result step.

### Stable local frontend verification

`infra/docker-compose.preview.yml` builds/runs the real frontend `prod` target
against the **existing local** backend, auth and synthetic records. It removes
development bind mounts; it is not a production deployment or backend rehearsal.
The build/typecheck passed on 7 September. Tests must finish before swapping it:

```bash
docker compose --env-file .env -f infra/docker-compose.yml \
  -f infra/docker-compose.preview.yml up -d --build --no-deps frontend
docker compose --env-file .env -f infra/docker-compose.yml restart nginx
```

Restore hot reload after the preview:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d --no-deps frontend
docker compose --env-file .env -f infra/docker-compose.yml restart nginx
```

**Runtime handoff state, 7 September:** restored successfully. The frontend's running
command is `npm run dev`; `/login` and `/api/v1/health` both return HTTP 200.
The local preview image remains available for a repeat demonstration. At the
end of verification this work was uncommitted; the subsequent user-requested
publication targets staging on `fix/billing-abdm-readiness`, without merging or
deploying it. `.env` and the supplied Postman files are excluded from the PR
and unchanged. The operator handoff is
[`ABDM-M1-M2-M3-Execution-Requirements-2026-09-07.md`](ABDM-M1-M2-M3-Execution-Requirements-2026-09-07.md),
with an editable Word version beside it.

Do not disable Next's memory protection or call repeated diagnostic retries a
passing first-load gate. Use the preview for demonstration/build verification;
the development runtime may still need memory sizing/profiling for long sweeps.

## Current ABDM readiness — measured, not assumed

| Area | Current evidence | Remaining prerequisite |
|---|---|---|
| Gateway session/registration | Authenticated service lookup HTTP 200; configured HIP/HIU service IDs are active | Recheck on demonstration day; do not recreate them unnecessarily |
| Public callback host | `https://abdm.healthdoc.world/api/v1/health` returned **HTTP 530 / Cloudflare 1033** | Restore the existing tunnel connector/origin before any M2/M3 attempt |
| Local tunnel target | Config now targets `https://localhost:443`, not the backend port | The September 2 document's bypass diagnosis is historical; connector availability and edge protection still need verification |
| Facility identity | Exactly one local facility matches configured HIP service ID | Ensure the same mapping in the environment demonstrated to NHA; this alone is not independent HFR registration evidence |
| M1 certificate | Live ABHA public certificate HTTP 200; configured key matches | Keep monitoring rotation; published algorithm is `RSA/ECB/OAEPWithSHA-1AndMGF1Padding` |
| M1 staff workflow | Reception's ABHA enrol/login panel exists; encryption/parsing corrected here | Real consenting sandbox-person OTP, read-back and failure/retry evidence still required |
| M1 feature breadth | Aadhaar enrolment and existing-number mobile OTP implemented | Mobile-verification continuation, ABHA-address selection/creation, card/QR/profile download and additional methods in the collection are not implemented as complete product workflows; obtain NHA's exact applicable mandatory test cases |
| M2 discovery/linking | Official callback routes, outbound replies and care-context API exist | Zero contexts/links; no staff UI/automatic context creation; **OTP relay URL and token both unset** |
| M2 HIP-initiated linking | Generator helper and receiving callback exist | No application caller starts `generate_link_token` and creates its correlated pending link. Calling the gateway manually alone will not establish that state |
| M2 transfer | Scoped FHIR builder, crypto and transfer worker exist | Real reference-HIU retrieval, consent revoke/expiry and actual transferred-bundle validation not demonstrated |
| M3 consent/data receive | Staff APIs, callbacks, encrypted push/decrypt and receipt notification exist | No frontend callers for `/abdm/hiu/*`; no clinician record viewer/import workflow. Received plaintext is placed on the outbox but no dedicated consumer for that event was found |
| Durability/retention | Requests are recorded; keys cleared on completion/revocation/access-time expiry | BackgroundTasks is not a durable job runner. Restart/retry recovery and scheduled expiry/erasure evidence remain needed |
| Callback origin trust | Header, recipient, timestamp and replay checks exist | Those are public values, **not origin authentication**. No source restriction is configured in the checked-in nginx files; any external WAF policy was not verified |
| Clinical FHIR | Existing docs claim six NRCeS-validated sample shapes | This review did not rerun the official validator. Validate the actual documents transferred during the demo, not only hand-created samples |

The certificate metadata above came from the official
[ABHA certificate endpoint](https://abhasbx.abdm.gov.in/abha/api/v3/profile/public/certificate)
using the configured sandbox session. The key and credentials were not printed.

### Additional correctness risks to address before broader M3 testing

- HIU requests now **enforce CAREMGT**. Other purposes need an explicit validated
  product mapping before being re-enabled; never silently substitute a purpose.
- Some staff mutation routes check the presence of Idempotency-Key without
  implementing a durable response replay. Test duplicate requests and gateway
  outages; a header alone is not idempotency.
- M1's stored field is named `abha_linking_token_encrypted`, but the enrol/login
  response credential is an ABHA account token. It is not automatically the
  HIP `X-LINK-TOKEN`. The latter comes from generate-token/on-generate-token;
  never substitute one credential for the other.

## Supplied Postman pack

Read **8 collections / 398 requests** and inspected the four environment-file
inventories without printing values. The reference directory is already ignored
by git and no files from it are tracked.

- All **23 configured outbound path defaults** appear in the supplied pack.
  This is a path-presence comparison, not complete method/header/body coverage.
- The M1 example labelled 18 August 2025 has 143 requests. PHR&HIECM has 125.
  Their filenames do not establish that these are the latest September 2026
  certification requirements.
- There is **one hardcoded production-host request** and **one legacy session
  request**, plus separate production environments. Do not press Run Collection
  across the whole pack. NHPR, Face Auth, Scan & Pay, PHR/locker/subscription
  flows are not automatically part of HealthDoc's declared HIP/HIU M1–M3 scope.
- Both HIECM environment files contain populated credential/token fields.
  Treat these as secrets even if they may be examples. Never commit, screenshot,
  paste into tickets or upload them to third-party test platforms.

Reproduce the safe inventory and source hashes:

```bash
python3 scripts/check_abdm_collections.py
```

It does not execute Postman scripts, send requests or print body/header/environment
values. Confirm the applicable collection/checklist with the
[official sandbox portal](https://sandbox.abdm.gov.in/sandbox/v3/). That portal's
documentation is client-rendered and the requested documentation page could not
be read through the web reader in this review.

## Before the 7 September attempt — prerequisites owned by a person

1. Obtain NHA's **current M1/M2/M3 test-case sheet**, your registered scope, demo
   booking and access to the reference HIP/HIU/ABHA applications. NHA's FAQ
   describes EMRSBX and requesting reference-HIU access. Do not wait until the
   demo to discover an account is unavailable.
2. Arrange a consenting sandbox test person and their OTP-capable phone; agree
   on synthetic clinical data and redacted evidence. Do not give an AI, another
   developer or a public ticket the Aadhaar/OTP/client secret.
3. Have the infrastructure owner investigate Cloudflare 1033 and restore the
   registered connector. Retain the nginx origin, verify its certificate trust,
   and test after restart. Avoid blind tunnel/bridge re-registration.
4. Agree a supported source-authentication/ingress control with NHA. Do **not**
   put an interactive Cloudflare Access login or a private custom-secret header
   in front of gateway callbacks unless NHA agrees to send it. Direct HIP→HIU
   pushes also come from external HIPs, not just gateway IPs, so blanket gateway
   allowlisting cannot cover every route. Keep real clinical data out until
   this boundary is reviewed.
5. Configure a real HTTPS link-OTP delivery relay using
   `ABDM_LINK_OTP_DELIVERY_URL` and `ABDM_LINK_OTP_DELIVERY_TOKEN`; test delivery,
   expiry, wrong code and retry limits. Never use a constant development OTP.
6. Review/apply this branch to the demo runtime and rerun gates. No direct-main
   promotion: retain feature → staging → main review policy.

## 7 September execution sequence

### 08:00–09:00 IST — go/no-go

```bash
make ps
python3 scripts/check_abdm_collections.py
./scripts/abdm_sandbox.sh token
./scripts/abdm_sandbox.sh services
./scripts/abdm_sandbox.sh doctor https://abdm.healthdoc.world
```

These existing script commands read `.env`; do not enable shell tracing or share
raw outputs that might identify accounts. The `doctor` command sends empty
callback probes: reject them, do not accept them as events. A 400/401/422 proves
reachability only, not a working valid callback. 1033/530, 502, 404, or accepted
empty callbacks are **stop conditions**. Verify NHA's actual callback request
arrives and is accepted before starting patient workflows.

Review `git diff`, run `make test-pg`, frontend tests/typecheck/lint and
`make contract`. Run browser suites **after** the PG suite, not concurrently.
Use the sandbox environment, gateway `https://dev.abdm.gov.in`, ABHA origin
`https://abhasbx.abdm.gov.in/abha/api`, and `X-CM-ID: sbx`.

### 09:00–11:00 — M1: identity, through the product

1. Sign in as the real test receptionist at `https://localhost`, open
   `/receptionist/registration`, search/select the synthetic local patient.
   Prefer verifying an existing ABHA over creating an unnecessary new one.
2. In the ABHA panel choose existing-number OTP; enter the person's own number,
   request OTP, let the person enter it, verify. Check the number/address belong
   to that same patient after a fresh reload. The token must not appear in the
   browser response/logs/evidence.
3. Separately demonstrate Aadhaar enrolment only where the test person and
   NHA's test case require it. Verify an address list does not cause a 500.
4. Exercise wrong/expired OTP, duplicate ABHA against another local patient,
   wrong role/facility and safe error messages. Mask all identifiers in evidence.
5. Execute any mandatory address/mobile/card/QR/profile cases on the actual
   product. **If they are mandatory, the missing workflows must be built; a
   manual Postman success is not proof that HealthDoc supports them.**

### 11:00–14:00 — M2: HealthDoc as HIP

1. Create clinically coherent **synthetic** encounters/orders/results in the
   product for the verified test patient. Use completed/signed records, not
   fixture charts. Confirm HI types match what the builders can produce.
2. Until staff tooling exists, an authorized doctor/admin can register a
   context using `POST /api/v1/abdm/hip/care-contexts`, a **HealthDoc Keycloak
   bearer** and Idempotency-Key. Required body: `patient_id`, `visit_id`, unique
   `reference`, meaningful `display`, supported `hi_type`. Take local IDs from
   actual records, not made-up UUIDs. This is API-only setup, not finished UI.
3. Use the patient's sandbox ABHA app for **patient-initiated** discovery → link
   initiation → OTP confirmation. Check the local context link becomes
   `confirmed`, and the app shows the same context. This path requires the relay
   configured before this attempt. Do not bypass it with a fabricated callback.
4. Through the reference HIU request limited access; the person grants it in
   the ABHA app. Observe HIP consent notify + acknowledgement, HI request +
   acknowledgement, encrypted data push, reference-HIU decrypt/display and
   completion notification. Preserve correlation IDs and timestamps.
5. Validate the **actual sent** FHIR bundle using the official validator and
   the NRCeS package/version NHA requires. Test narrowed types/date ranges,
   revocation, expiry, wrong references and tampered/duplicate requests.

Official callback path reference:
[NHA GatewayURL.java](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/common/constants/GatewayURL.java).

### 14:00–17:00 — M3: HealthDoc as HIU

1. Prepare records linked to the same test person's ABHA at the **reference HIP**.
   Self-exchange within HealthDoc alone does not establish interoperability.
2. As doctor/admin, call `POST /api/v1/abdm/hiu/consent-requests` with a Keycloak
   bearer and Idempotency-Key. Body: `patient_id`, `abha_address`,
   `purpose_code: "CAREMGT"`, supported `hi_types`, UTC `date_range_from`,
   `date_range_to`, and future `requested_expiry`. Request the minimum scope.
3. Save the **local** returned request ID. The person approves in their app.
   Observe on-init, notify/acknowledgement and on-fetch. Read
   `GET /api/v1/abdm/hiu/consent-requests/{local_request_id}/artefacts`.
4. Use the granted artefact's **local row ID**, not its gateway ID, for
   `POST /api/v1/abdm/hiu/artefacts/{local_artefact_id}/health-information`.
   HealthDoc sends the artefact's granted dates and its public key material.
5. Confirm a real HIP POST reaches
   `/api/v3/hiu/health-information/transfer`, decrypts with matching request
   state, stores receipt/checksum evidence and sends its completion notification.
6. **The clinician must be able to view/use the received document through a
   properly scoped product workflow. That viewer/import leg is still missing.**
   A receipt row or plaintext queued on the outbox alone is not completion.
7. Prove revoked/expired consent, bad GCM authentication, duplicate/paged pushes,
   wrong transaction/facility and key cleanup. Test server restart mid-transfer.

### 17:00–18:00 — evidence and submission

For each required case, capture: case ID, source commit, environment, role,
redacted screenshot, sanitized request/callback correlation IDs, actual result,
expected result, bundle validation result and pass/fail. Never export raw HARs
containing bearer tokens/ABHA/Aadhaar/OTP/clinical data into git.

Mark blocked cases **blocked**, not passed. Submit/request review in the NHA
portal only for what actually ran. Ask NHA to confirm remaining scope and demo
acceptance; do not announce production approval on the strength of this run.

## Realistic completion target

- **7 September:** a verified M1 core OTP journey and an operator-led M2/M3 technical
  exchange are possible only if tunnel, OTP delivery, reference apps/person and
  required clinical context preparation are ready. No such exchange is proven
  in this review. Missing mandatory M1 cases can still stop the milestone.
- **Product-level M1–M3:** provisionally **3–7 engineering days** for the remaining
  staff context/link tooling, HIU viewer/consumer, applicable M1 workflows and
  recovery/retention work, plus actual sandbox regression. This is a planning
  estimate, not a commitment; NHA's applicable checklist may expand it.
- **Certification/production approval:** depends on NHA review and independent
  testing/security assessment; it cannot honestly be promised for 7 September.

Other project coverage still to extend: pharmacy checkout UI for its scoped
invoice APIs, full settlement/print edge cases, independent lab release,
inventory approval chains, nursing-handover edge cases, staff creation,
and production recovery/load tests. This review is not an exhaustive guarantee
that every project feature is correct.
