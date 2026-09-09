# Tariff management — implementation and acceptance, 9 September 2026

## Branch and publication

The preceding invoice-switch fix is committed as `705c682` and published in
[PR #543 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/543).
All four active checks passed, including `nurse-auth-e2e`; electron packaging
was skipped, not tested.
This next work is prepared for staging review on **`feat/billing-tariff-management`**,
based on that commit. It is not included in PR #543. No main PR, merge or
production deployment was performed in this turn.

## Built

- `/billing/tariffs`: facility catalogue with search, pagination, effective-date
  history and an explicit include-retired filter. Navigation is offered only
  to billing/admin; existing `/billing` route guards already restrict it to
  those roles. The new route is included in both role smoke matrices.
- New version and revision forms with required fields, category, exact decimal
  price, valid date and optional scheme. Review precedes saving. A revision
  keeps the original code/category/scheme fixed; changes create a new row.
- Retirement confirmation names the version and explains that retiring can
  affect unbuilt historical charges or leave services unpriced. Retirement
  keeps history; it is not deletion or a change to posted invoice lines.
- Corrected the list adapter: `Envelope.data` is an array, and
  `active_only=false` must be sent to the server to retrieve retired rows.
  The DTO now matches `TariffOut` (decimal-string price, no invented audit
  fields). Missing or failed responses do not become empty success.
- Fixed shared API handling of successful **HTTP 204**. Previously a successful
  retirement was reported as a failed JSON parse. Empty 200/error responses
  still fail; only an actual 204 bypasses envelope parsing.
- Kept dormant add-item UI compatible with the corrected DTO and added failure
  handling. **Manual invoice editing remains disabled**; no client-side tariff
  resolver was added.
- Added the tariff browser workflow to CI with synthetic-only writes. This new
  branch's CI changes have not run on GitHub yet.

## Verification

- **62 frontend unit tests passed**, including nine new contract, validation,
  role-guard and 204/error regressions. The catalogue-array and bodyless-204
  tests both failed on the original code before repair.
- Typecheck and scoped ESLint passed without warnings on changed application
  files. The production webpack build passed and includes `/billing/tariffs`.
  **207 frontend API calls match OpenAPI**; generated contract matrix
  updated. This gate checks paths/methods, not full wire semantics.
- **9/9 real-login browser checks passed**, final run
  `tariff-management-r2-20260909`: invalid form/no POST, billing create, revision
  and original-price preservation, explicit zero scheme rate, real server
  conflict, real 204 retirement/history, injected catalogue outage/retry,
  independent admin retirement/read-back, and receptionist route/menu/API denial
  for reads and both writes.
- Real local backend requests were used except the explicitly injected 503
  catalogue-read outage. The UI did not invent financial responses. A unique
  `SYNTH-…` code was created per run; no existing hospital tariff was modified.
- The initial unit harness used TypeScript's legacy default target, which
  miscompiled string iteration. It was corrected to ES2020; the application's
  validation logic was not relaxed. The first browser run passed with admin
  read-only acceptance; the final rerun additionally proves an admin write.

Evidence is retained locally under
`docs/evidence/tariff-management-r2-20260909/` (`tariff-management.json` and nine
screenshots). Synthetic rows remain for inspection, including the untouched
scheme row. Earlier run evidence is separate. No full backend/whole-role rerun
or real ABDM transaction is claimed for this frontend change.

## Deployment and remaining limits

1. The application remains on migration **0067**. Apply/rehearse **0068** through
   the reviewed deployment process before relying on next-day revisions that
   close the old version on its start date. Browser acceptance here uses a
   two-day gap and does not pretend to exercise 0068 on the application DB.
2. Hospital finance must approve exact service codes, scheme codes, prices and
   effective dates. The synthetic prices are not an approved fee schedule.
3. The current backend tariff routes do **not** implement idempotency replay
   or a complete concurrent-revision locking contract. The UI prevents duplicate
   clicks, sends an action key and never automatically retries a write. After
   failure it requires closing and reading the catalogue before another attempt.
   Server-side replay/serialization and concurrent-writer acceptance remain a
   hardening task; a frontend key does not establish them.
4. No restore/reactivation or arbitrary end-date-edit endpoint was invented.
   The server closes the previous open version when a new version is created.
   Closed historical rows may remain enabled for their date range.
5. Mobile/keyboard/accessibility coverage, unbounded catalogue scale, real
   invoice/receipt edge cases and the other clinical workflows remain separate
   acceptance work. The sidebar matrix now contains **51** role/screen pairs;
   adding two entries is not proof of a new full 51-screen pass.
6. ABDM M1–M3 work is unchanged by this feature. Continue from the current
   [ABDM status and closure sequence](bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md#implementation-update--9-september-2026).

## Repeat locally

Use only a configured synthetic local stack. Keep the ABDM delivery worker
stopped and avoid heavy backend tests concurrently with browser runs.

```bash
cd frontend
npm test
npm run typecheck
E2E_BASE_URL=https://localhost E2E_ALLOW_MUTATIONS=1 \
  E2E_RUN_ID=tariffs-your-new-id \
  E2E_EVIDENCE_DIR=../docs/evidence/tariffs-your-new-id \
  npm run test:tariff-management
npm run build -- --webpack
```

Next bounded work: strengthen tariff server replay/concurrent revisions, then
the external-referral result intake UI (F04). eMAR writes still require the
clinical dose-identity/concurrency decision documented in F03.
