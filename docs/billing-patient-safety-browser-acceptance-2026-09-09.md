# Billing and patient safety — local browser acceptance, 9 September 2026

Branch: `fix/billing-tariffs-patient-safety`; acceptance tested the then-uncommitted work based on
`151f6c754868ba8ef9adde699f6d2acb8c50c716`.
Target: `https://localhost`, local Docker backend/auth and real Keycloak
development accounts. The final sweep uses the frontend's production-preview
image, not hot reload. This is not a production deployment or ABDM certification.

## Retest status

**PASS — all configured gates below completed; this is not whole-product or
ABDM milestone sign-off.**
Final run identifier: `billing-safety-20260909-preview-r3`.
Evidence is local and gitignored under
`docs/evidence/billing-safety-20260909-preview-r3/`. Do not use intermediate
screenshots or a manifest with `completed: false` as sign-off.

| Final gate | Result | Evidence / scope |
|---|---|---|
| Dashboards | **49/49**, 14 roles | [Manifest](evidence/billing-safety-20260909-preview-r3/dashboards.json); no failed API/asset requests, errors or recovery warnings in the captured screens. |
| Workflows | **10/10 groups, 43 steps** | [Manifest](evidence/billing-safety-20260909-preview-r3/workflows.json); billing/refund, inventory tabs, maintenance, emergency maker-checker merge/unmerge, auditor, patient portal, IPD/nursing, OPD/lab/radiology, public queue, non-OPD visits. |
| Superadmin isolation | **Passed** | [Manifest](evidence/billing-safety-20260909-preview-r3/superadmin.json); platform API allowed, five facility APIs refused, three facility UI routes redirected; one captured composite step. |
| Patient-switch fault injection | **7/7** | Real login/rendered UI, deliberately simulated patient/OTP transport; detailed scope below. |
| Tariff build → full payment | **5/5** | Real Keycloak/APIs and billing UI; detailed scope below. |
| Login/accessibility/keyboard | **9/9 roles** | `test:e2e` exited 0; required bearer call, forbidden-route redirect, keyboard skip link, silent SSO 200 and no serious/critical Axe findings on those states. |
| Print CSS smoke | **4/4** | `test:print` exited 0; synthetic prescription, receipt, lab report and MIS markup generated valid nonempty PDFs. |

The three role manifests pass the existing `run_errors` and `run_warnings`
validators with empty results. The two target manifests are completed/passed
and share the same run ID. **105 referenced screenshots** across those five
manifests exist locally. No failed development evidence was overwritten.

The final preview used image
`sha256:99d035926aea63f81615942cd6a45a956027a0cd4bec12c954cd3c698a9961b4`
with `npm run start`, beginning 2026-09-09 13:33:31 UTC. Proxy logs from that
start through the final checks recorded zero rate-limit refusals, upstream
connection refusals or upstream timeouts. The authentication gate logged
aborted navigation/prefetch/teardown requests; its required checks all passed.

The preceding strict run in `docs/evidence/billing-safety-20260909-r2/` passed
49 configured screens and 10 workflow groups/44 recorded steps, but predates
the last fixes below. It is historical evidence, not a substitute for the
final sweep.

The later development run `billing-safety-20260909-final-r2` failed at
**48/49 screens**: `/doctor/orders` lost its JavaScript/fonts to HTTP 502 when
Next.js logged a memory-threshold restart. Its screenshot shows an unstyled
loading screen and zero API requests. The failed manifest is preserved; it is
not relabeled as passing after a retry. No memory safeguard was disabled.

## Defects reproduced and fixed during acceptance

| Defect | Evidence before the fix | Fix and regression proof |
|---|---|---|
| Patient access race | A delayed access approval for patient A unlocked the rendered panel after switching to denied patient B. | Key the access gate by patient, including consent/grant/dialog state. Deferred component test and browser fault injection now keep B locked. Backend authorization remains independent. |
| Missing tariff provenance in invoice responses | The browser built a correctly priced line, but invoice detail omitted its `charge_master_id`. | Include the persisted identifier in `InvoiceLineOut`. The HTTP regression failed before the schema change and passed afterwards; browser read-back now verifies it before and after payment. |
| Stale payment balance | The invoice showed ₹463.27 while collection still validated against its original ₹50.00 balance. | One coherent payment/detail read, invoice/revision-scoped state, stale-response rejection and disabled controls while unavailable. Hook regressions pass; the browser pays the exact ₹463.27 and reads back zero outstanding. |
| Newly reported vulnerable dependencies | A fresh `npm ci`/audit reported two high and one critical affected packages, despite the historical clean audit. | Updated Next.js and eslint-config-next to locked 16.3.4, sharp to 0.35.4 and js-yaml to 4.3.2. Fresh host audit and image dependency install report zero known vulnerabilities. |

Earlier tariff-resolution and patient-summary/ABHA state fixes are described
in [the implementation note](billing-patient-safety-fixes-2026-09-09.md).

Dependency patch thresholds were checked against the published advisories:
[Next.js image optimization](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4),
[Next.js Windows hosting](https://github.com/advisories/GHSA-p293-qw3h-jr36),
[sharp/libheif](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c), and
[js-yaml resource exhaustion](https://github.com/advisories/GHSA-2883-xcg3-v3hh).
These are dependency findings, not evidence that this local application was
exploited. The package manifest, npm lockfile and npm-synchronized yarn lockfile
are all updated; no unrelated dependency major upgrade was requested.

## Source gates

- `make test-pg`: **1,507 backend tests + 14 script tests passed**. Four ABDM
  Pydantic alias warnings remain; a passing suite does not erase those warnings.
- Targeted PostgreSQL billing/HTTP tests: **34 passed** after the response fix.
  The tariff/migration subset covers **22 tests**, including temporary-table
  migration upgrade/downgrade checks and preservation of one-day tariff history.
- Frontend unit gate: **46 passed**, including a repeat after dependency
  updates. TypeScript passed on the patched dependencies.
- Final `make audit-deps`: backend pip-audit and production frontend npm audit
  both report **zero known vulnerabilities**. The separate full frontend
  dependency audit, including development dependencies, also reports zero.
- Changed Python files: Ruff passed. Changed frontend source/tests: ESLint
  passed. These are scoped checks, not a claim that all untouched code is lint-free.
- `make contract`: **205 frontend calls matched OpenAPI**. This checks route
  coverage, not every payload or external ABDM protocol exchange.
- Production frontend build: Docker `npm run build` passed with **Next.js
  16.3.4 / Turbopack**, including TypeScript and route generation. Both the
  complete image dependency install and production prune audit reported zero
  known vulnerabilities. The patched preview image built and started successfully.
  This distinguishes the earlier host-specific build restriction from an
  application compile failure. The prior webpack build also passed.

## Targeted browser acceptance

### Billing tariffs: 5/5 checks passed

Manifest: [billing-tariffs.json](evidence/billing-safety-20260909-preview-r3/tariffs/billing-tariffs.json).
All identities sign in through Keycloak. No application API response is mocked.
The test creates unique synthetic tariff codes, patient, day-care visit and two
radiology orders. Clinical setup/scheduling/finalization is performed through
real authenticated APIs from the browser, not by clicking every clinical form.

1. Billing UI build charges the configured ₹413.27 tariff and reports the
   second unpriced source; it does not create an assumed-zero line.
2. Repeating build adds no duplicate or repriced line.
3. Explicitly configuring the second synthetic tariff as ₹0.00 creates a
   valid free line and clears the missing-price warning.
4. UI issue and full collection reconcile the existing ₹50.00 registration
   plus ₹413.27 charge, preserve tariff identifiers and leave no balance.
   Assertions use integer paise/Decimal strings, not floating-point arithmetic.
5. A real pharmacist token receives 403 for the mixed non-pharmacy invoice.

### Patient switching: 7/7 checks passed in the final sweep

Manifest: [patient-switch.json](evidence/billing-safety-20260909-preview-r3/patient-switch/patient-switch.json).
This suite uses real Keycloak and real rendered
components, but **simulated patient reads and ABHA transport**. It proves UI
state isolation, not a live OTP, clinical consent grant or NHA round trip.

- Immediate patient changes clear the doctor's old summary.
- Delayed demographics, allergy and history responses do not replace the next patient.
- Failed allergy/history reads display unavailable states, not “none recorded”.
- Retry fetches the data again and restores the summary.
- A late access approval cannot unlock a different denied patient.
- Reception discards the previous patient's pending OTP/session response.
- A late verification success cannot mark the newly selected patient as linked.

Every ABHA API request from the exercised panel is intercepted, including
unexpected ones, so no external OTP is sent by this test.

## Operational notes and failures retained

- At the beginning of acceptance the local proxy returned 502. Subsequent
  inspection found the stack's containers stopped. Starting the existing
  local services restored them; no database was wiped, no realm reseeded and
  no proxy authentication rule weakened. The ABDM delivery worker was not started.
- Earlier failed target runs are retained. They include the three reproduced
  defects above and corrected harness assumptions: a timestamp already in the
  past, StrictMode producing multiple requests, and a valid Decimal zero
  serialized as `"0"`. Those failures are not counted as passing acceptance.
- One patient-switch attempt stalled before Keycloak sign-in. A separate
  strict rerun completed without recovery. Its cause was not established;
  there is no evidence supporting a rate-limit diagnosis for that attempt.
- Heavy PostgreSQL tests and browser suites are run sequentially to avoid
  known local runtime contention. Browser recovery remains disabled.
- Final browser acceptance uses `infra/docker-compose.preview.yml` to remove
  dev-server hot reload from the test runtime, following the existing local
  runbook. Only the frontend is rebuilt/replaced; nginx is restarted to resolve
  its Docker address. Backend/auth/databases remain in place. After the tests,
  the development image was rebuilt with the patched dependencies and hot
  reload restored; this avoids reverting to the old vulnerable image.
  Handoff checks confirm `npm run dev`, Next.js 16.3.4, `/login` HTTP 200
  and `/api/v1/health` HTTP 200.
- Synthetic records, tariff versions and financial writes remain in the local
  application database for inspection. Existing approved prices were not
  altered. No commit, push, PR, merge, production change or real ABDM exchange
  was performed in this acceptance pass.
- The complete role rerun records 43 workflow steps rather than the earlier
  44: setup is conditional on the already-open local queues. The authoritative
  count is all 10 planned workflow outcomes, not an assumed constant number
  of setup screenshots.

## Remaining release acceptance — do not call this “everything tested”

1. Apply migration **0068** through the reviewed deployment process. The local
   application remains on 0067; the isolated PostgreSQL test database exercises
   0068. Rehearse same-day/next-day tariff revisions in the deployment copy.
2. Configure finance-approved tariffs with exact lab codes/radiology modalities,
   schemes and effective dates. The new synthetic prices are not a fee schedule;
   a complete tariff-administration UI remains a separate work package.
3. Independent lab verification/release still needs a second authorized
   technician identity in the browser scenario. Preliminary results and
   self-verification refusal are not final lab release acceptance.
4. The screen sweep does not prove every mutation: full pharmacy dispensing,
   inventory approval chains, staff administration, nursing eMAR/fluid balance,
   and exhaustive failure/concurrency scenarios need action-level checks.
5. The subsequent [invoice-switch follow-up](invoice-switch-safety-2026-09-09.md)
   reproduces and fixes the cross-invoice workspace race, with seven browser
   delay checks and a fresh real billing/refund regression. Those are separate
   results, not part of this tariff run. Exhaustive refund/receipt concurrency
   and edge cases remain open.
6. Print smoke renders minimal synthetic markup with the application's print
   CSS. Actual prescription/report/receipt contents, pagination and physical
   printer output still need review. Axe checks cover only visited states,
   not all accessibility requirements.
7. M1–M3 still require authorized real sandbox participants, OTP/consent actions,
   reachable callbacks, end-to-end encrypted transfer/decryption, clinical FHIR
   validation and NHA evidence/approval. None is inferred from these local gates.

## Reproduce the local acceptance

Run against an already configured **local** synthetic-data stack. Use a fresh
identifier and evidence directory for each complete run; do not mix manifests.
Keep the ABDM delivery worker stopped for these synthetic clinical fixtures.
For the complete sweep, first select the production preview as documented in
[Stable local frontend verification](billing-abdm-readiness-2026-09-06.md#stable-local-frontend-verification).

```bash
make test-pg
make contract
cd frontend
npm test
npm run typecheck
export E2E_BASE_URL=https://localhost
export E2E_RUN_ID=your-new-unique-run-id
export E2E_ALLOW_RECOVERY=0
export E2E_EVIDENCE_DIR=../docs/evidence/your-new-unique-run-id
npm run test:dashboards
E2E_ALLOW_MUTATIONS=1 npm run test:workflows
npm run test:superadmin
E2E_ARTIFACT_DIR="$E2E_EVIDENCE_DIR/auth" npm run test:e2e
npm run test:print
E2E_EVIDENCE_DIR="$E2E_EVIDENCE_DIR/patient-switch" npm run test:patient-switch
E2E_ALLOW_MUTATIONS=1 E2E_EVIDENCE_DIR="$E2E_EVIDENCE_DIR/tariffs" npm run test:billing-tariffs
npm run build -- --webpack
```

After preview acceptance, restore the patched development image rather than
an old cached image:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d --build --no-deps frontend
docker compose --env-file .env -f infra/docker-compose.yml restart nginx
```

Run those restore commands from the repository root. Long development-server
sweeps can still reach Next's memory threshold; the production preview is the
measured stable acceptance runtime, not a claim that dev memory behavior was fixed.

The targeted suites fail closed with incomplete/failed manifests. Evidence
contains synthetic screenshots and record IDs, not bearer tokens or secrets.
The older evidence generator defaults to `docs/evidence/roles`; do not run it
against a different directory and assume it read these dated artifacts.
