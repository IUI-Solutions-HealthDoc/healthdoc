# Billing tariffs and patient-switch safety — 9 September 2026

Branch: `fix/billing-tariffs-patient-safety`. Implements the initial F01/F05
work from the HealthDoc–Bahmni handoff, not all 32 work packages.

## Behavior changed

- Automatic finalized lab and radiology charges resolve the existing
  `charge_master`, scoped to facility, category, invoice scheme and the recorded
  visit's facility-local date. A scheme rate takes precedence over general.
- Each new departmental invoice line pins the tariff UUID and Decimal amount.
  Existing lines are never repriced; issued invoices remain frozen. Pharmacy
  continues using its batch rate and its existing narrow billing authority.
- No runtime sample lab/imaging prices remain. Missing, inactive, expired,
  future, foreign-facility or wrong-category tariffs remain visibly unpriced;
  the existing builder reports/skips them, never inserts assumed zero charges.
  An explicitly configured zero price is different and remains a valid tariff.
- Preview responses include `charge_master_id`, `charge_code`, `pricing_date`;
  manual invoice editing remains disabled. Existing build feedback reports
  unpriced lines. A full tariff-maintenance UI is still the separate F02 task.
- Invoice detail responses now also retain `charge_master_id`. Browser
  acceptance found that the line was correctly pinned in PostgreSQL but its
  response schema discarded the identifier on read-back.
- Payment history and balance come from one invoice-detail response. Changing
  the invoice or its financial revision invalidates the old balance immediately;
  delayed responses cannot replace the current payment snapshot. Collection and
  refund controls stay disabled while this read is pending or failed, and open
  payment dialogs reset on invoice/revision changes. This fixes the reproduced
  case where a ₹463.27 invoice still offered a ₹50.00 payment balance.
- The ABHA component itself owns a patient-keyed boundary, so every caller
  discards old identifier/OTP/session/success state on patient changes. Late
  responses from previous patients/flows are ignored, duplicate in-flight
  clicks are suppressed, and a mismatched binding cannot show success.
- The doctor's summary resets before rendering another patient. Demographics,
  history and allergies have independent loading/success/error states and a
  retry action. A failed read never becomes “none recorded” or “first visit.”
- The record-access gate is patient-keyed too. A delayed access approval for A
  cannot unlock B's chart or preserve A's emergency-access dialog. The browser
  fault-injection test reproduced this race before the additional fix; backend
  consent checks were not relaxed.
- A fresh build exposed new dependency advisories. Next.js and its ESLint
  configuration now resolve to 16.3.4, sharp to 0.35.4, and js-yaml to 4.3.2;
  both lockfiles are synchronized. The fresh npm audit reports zero known
  vulnerabilities. Advisory references and runtime acceptance are in the
  dated browser report.

## Deployment/configuration requirements

Apply migration **0068** through the reviewed deployment workflow before using
next-day tariff revisions. It changes only the inclusive date CHECK from `>`
to `>=`: the existing resolver already includes both endpoints, and the tariff
service ends the previous price one day before its replacement. The old CHECK
incorrectly rejected a price valid for one day. No price rows are rewritten.
Downgrade refuses when one-day rows exist; financial history is not deleted or
extended to make rollback pass.

Billing/admin must configure approved tariffs through the existing
`POST /api/v1/billing/charge-master` workflow:

- Lab: `charge_category=lab`, exact source `test_code` as `charge_code`.
- Imaging: `charge_category=radiology`, exact source `modality` as
  `charge_code` (for example `xray`). This retains the existing modality-level
  model; free-text scan names do not become tariff keys. Per-procedure imaging
  pricing needs a separately approved source-code mapping.
- Use finance-approved amounts, effective dates and scheme codes; do not copy
  synthetic test prices into an application or production facility.

Reopening an old visit uses its original business date. A tariff beginning
today cannot silently price yesterday's missing work. Existing supersession,
deactivation and general-rate fallback policy is preserved.

No application database migration, real OTP, ABDM transfer, push, PR or
production promotion was performed for this work. The separate PostgreSQL
test database exercises migration 0068. Browser acceptance creates uniquely
named synthetic patients, clinical records, tariffs, invoices and payments in
the local application database; these remain available for inspection. It does
not change an existing approved tariff. The local ABDM delivery worker remains
stopped; synthetic clinical records must not be used as sandbox clinical evidence.

## Verification and remaining acceptance

The new PostgreSQL tests seed clinical source records independently of tariffs.
Before the fix they reproduced the old static-price behavior. Cases cover
both departments, wrong/missing catalogue rows, source identity, decimal wire
amounts, scheme fallback/priority, local-midnight and effective-date boundaries,
exact tariff persistence, repeated builds and unchanged posted/issued amounts.
The existing concurrent-build, payment/refund and pharmacy-authority tests
remain part of the regression gate.

Frontend tests execute the actual TSX with deferred transport and a minimal
key/effect harness: immediate patient switches, stale successes/failures,
StrictMode replay, independent read failures/retry, null demographics,
duplicate OTP clicks, flow changes and binding mismatch. These are component
regressions, **not** an NHA OTP demonstration. Separate browser acceptance now
uses real Keycloak and the rendered application; the patient-switch suite
deliberately intercepts patient reads and every ABHA API request to inject
delays and failures without sending OTPs.

The following local browser checks have now passed; see the
[dated browser acceptance report](billing-patient-safety-browser-acceptance-2026-09-09.md)
for run identifiers, broader gates and remaining limits:

1. Configure a known tariff, finalize synthetic imaging results, build the
   invoice, read it back, issue and pay the full balance; reconcile Decimal
   amounts and tariff UUID. Clinical setup/finalization uses real authenticated
   APIs; build, repeat-build, issue and collection use the billing UI. Final lab
   release by a second technician is not established by this browser test.
2. Leave another source code unconfigured: it must be reported unpriced and
   not silently included for zero. Confirm pharmacy cannot bill a mixed invoice.
3. On reception, delay patient A's OTP response, select B, and confirm A's OTP,
   masked destination and success never appear under B. Use mocked transport
   unless separately authorized for actual OTP sends.
4. In the doctor queue, switch A → B with delayed/failed allergies/history;
   confirm no A content, distinct unavailable state, and successful retry.

### Measured checks

- Final `make test-pg`: **1,507 backend tests + 14 script tests passed**;
  four existing ABDM Pydantic alias warnings. **75 migrations**, linear head
  **0068**. Explicit convention scan of all nine changed/new Python files:
  zero blockers/warnings (the default committed-diff scan misses local edits).
- Targeted PostgreSQL tariff/migration suite: **22 passed**. Includes actual
  upgrade → downgrade → upgrade on a connection-local temporary table,
  inverted-date refusal, and downgrade refusal without deleting a one-day row.
- `npm test`: **46 passed**, including **9 new patient-state regressions** and
  **3 payment-state regressions**.
  Temporarily replacing both patient keys with a constant caused three tests
  to fail; restoring the actual code returned the suite to green.
- `npm run typecheck`: passed. Changed-file ESLint and Python Ruff: passed.
  A wider Ruff probe reports pre-existing router warnings; no blanket lint-clean
  claim is made for untouched backend code.
- `make contract`: **205 calls matched**; this is URL coverage, not payload proof.
- `npm run build -- --webpack`: production build passed, including TypeScript
  and route generation. Standard `npm run build` remained blocked by a
  Turbopack subprocess/port-binding `Operation not permitted` error in this
  environment, including a permission-escalated retry. The subsequent Docker
  production-preview build also passed standard `npm run build` with Turbopack
  on the patched Next.js 16.3.4 dependencies. No build config or CI gate was
  relaxed to hide the earlier host restriction.
- Targeted tariff browser: **5/5 checks passed**, including a full ₹463.27
  payment, zero outstanding balance, explicit zero pricing and real pharmacist
  denial on a mixed invoice. Targeted patient-switch browser: **7/7 checks
  passed** with real sign-in and explicitly simulated patient/OTP transport.
- The final all-role browser retest is recorded separately in the dated report;
  prior runs are not substituted for a failed or incomplete final run.

This document does not claim the entire project or ABDM milestones are complete.
