# Invoice-switch safety and next work — 9 September 2026

## Delivery status

PR [#541](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/541) is merged
into staging; its four active CI checks passed. This follow-up starts from
staging merge `f82cd6c` on **`fix/billing-invoice-switch-safety`**. This follow-up
is prepared for staging review. No main promotion or production change was performed.

## Defect reproduced and fixed

Selecting invoice Beta while Alpha's detail request was pending could display
Alpha's patient/header under Beta's selection. Invoice editor, preview and
payment state also shared a lifetime across selections, allowing late actions
to update the wrong workspace.

- The detail hook now binds its snapshot to the selected invoice, hides stale
  identity immediately, ignores obsolete responses and rejects mismatched IDs.
  Mutation read-back invalidates earlier reads rather than allowing an older
  balance or status to replace it. Failed reads have a visible retry action.
- A keyed invoice workspace owns detail, editor, preview, payment and reversal
  state. Switching invoices discards those controls and dialogs together.
- In-flight writes are **not cancelled or redirected**: the original operation
  may finish for its original invoice. Its completion cannot replace the new
  workspace. Existing global completion toasts are not a new invoice-scoped
  notification system. Financial rules and backend permissions are unchanged.

## Fresh verification

| Gate | Result and scope |
|---|---|
| Frontend unit tests | **53 passed**, including seven new invoice-detail regressions. The first five failed against the original implementation before the fix. |
| Browser race suite | **7/7 passed** with real Keycloak sign-in and rendered billing UI; financial reads/writes intercepted to inject delays safely. |
| Real local billing workflow | Passed: synthetic visit → build → issue → ₹1.25 payment → separate admin ₹0.25 refund, persisted read-back and role refusals. No external payment processor. |
| Billing-role screen sweep | **2/2 passed**: `/billing` and `/reports`; no automatic recovery. This is a filtered run, not another full-project sweep. |
| Compilation | Typecheck, scoped ESLint and production webpack build passed. |
| CI wiring | New `test:invoice-switch` step added to `nurse-auth-e2e`; workflow YAML/script wiring validated locally. Not yet run on GitHub for this branch. |

Browser cases cover late detail response, immediate identity/dialog reset,
collection amount reset, failed read and retry, and late build/issue/payment
completion after switching. Modal-open switching is a deliberately forced UI
state-change stress test, not a claim that a user can click through a backdrop.
These tests do not establish every refund concurrency or receipt edge case.

Local evidence (gitignored; retained separately):

- `docs/evidence/invoice-switch-before-20260909/`: original browser failure.
- `docs/evidence/invoice-switch-fixed-r2-20260909/invoice-switch.json`: seven
  successful checks and screenshots.
- `docs/evidence/invoice-safety-real-billing-20260909/`: `workflows.json`,
  `dashboards.json` and real-API synthetic workflow/screenshots.

The first fixed browser attempt held Beta's follow-up balance read indefinitely
because the test harness did not clear its delay control. That failed run is
retained separately; the harness was corrected without relaxing assertions.

No backend code changed, so the full backend gate was not repeated here.
The prior 1,507 backend tests and 49-screen acceptance belong to the
[previous merged work](billing-patient-safety-browser-acceptance-2026-09-09.md),
not this fresh run. This browser pass used the local development frontend;
the separate production build passed but was not deployed for this pass.
Synthetic financial records remain in the local database. The ABDM delivery
worker was not started; no migration, real OTP or external transfer was run.

## What remains, ranked

1. **Next buildable work: tariff maintenance (F02).** Correct the catalogue list
   adapter to the backend's array response and add authorized create/history/
   deactivate UI using existing APIs. Cover effective dates, Decimal prices,
   scheme selection, conflicts and role denial. Update guards, sidebar and
   browser coverage together. Do not enable freehand invoice repricing.
2. **Deployment and approved configuration.** Rehearse/apply migration 0068
   through the reviewed deployment process and load finance-approved tariffs.
   The application remains at 0067; synthetic acceptance prices are not an
   approved hospital fee schedule.
3. **Clinical action gaps and acceptance.** eMAR recording needs agreed
   scheduled-dose identity, amendment and concurrent-administration policy
   before exposing writes. External referral result intake needs frontend
   integration. Independently verify final lab release with a second authorized
   technician, full dispensing, inventory approval chains and remaining
   staff/nursing actions. Screen loading alone does not close these items.
4. **Document and quality acceptance.** Verify actual prescriptions, reports
   and receipts, pagination and printer output; extend keyboard/accessibility
   checks and financial failure/concurrency cases beyond visited states.
5. **ABDM code and live acceptance, tracked separately.** M1 still needs
   continuation/account-credential lifecycle and persisted Scan-and-Share;
   discovery/link/profile response durability and missing asynchronous callback
   recovery remain. Clinical authorship/versioning, historical-content
   remediation and worker/restore recovery need closure. Then prove actual
   authorized participant OTP, consent, linking and encrypted transfer against
   reachable, approved ingress with verified registry/clinical inputs. NHA
   acceptance is external, not inferred from local tests. See the current
   [ABDM implementation-status table and next sequence](bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md#implementation-update--9-september-2026).

The wider [Bahmni functional handoff](healthdoc-vs-bahmni-functional-gap-and-frontend-handoff-2026-09-09.md)
remains the detailed backlog; its original findings must be read alongside
dated implementation reports. This follow-up closes the tested invoice-switch
gap, not every item in that backlog or M1–M3 certification.

## Reproduce this targeted pass

Use an already configured local synthetic-data stack. Keep delivery stopped
and run backend-heavy gates separately from browser tests. Use new run IDs and
evidence directories; do not overwrite the retained manifests.

```bash
cd frontend
npm test
npm run typecheck
E2E_BASE_URL=https://localhost E2E_RUN_ID=invoice-switch-your-new-id \
  E2E_EVIDENCE_DIR=../docs/evidence/invoice-switch-your-new-id \
  npm run test:invoice-switch
E2E_BASE_URL=https://localhost E2E_RUN_ID=billing-your-new-id \
  E2E_EVIDENCE_DIR=../docs/evidence/billing-your-new-id \
  E2E_ALLOW_MUTATIONS=1 E2E_ALLOW_RECOVERY=0 E2E_WORKFLOW=billing \
  npm run test:workflows
E2E_BASE_URL=https://localhost E2E_RUN_ID=billing-your-new-id \
  E2E_EVIDENCE_DIR=../docs/evidence/billing-your-new-id \
  E2E_ALLOW_RECOVERY=0 E2E_ROLE=billing npm run test:dashboards
npm run build -- --webpack
```
