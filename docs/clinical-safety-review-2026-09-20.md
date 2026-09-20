# Clinical safety and Keycloak review — 20 September 2026

Branch: `fix/clinical-safety-keycloak-return`. Base: `35d8cc4`.
Implementation and tests were performed in an isolated worktree; the other
agent's `feat/suite-9-portal-terminology-a11y-m1` workspace was not edited.
No production records, sandbox participant operations, credentials, outbound
ABDM jobs, remote branches or PRs were changed by this pass.

## Completion assessment

The repository now contains implementation commits through HD-36, including
Suites 7–9. That is implementation coverage, not 36 accepted packages or a
defensible whole-project percentage. This review found security and correctness
defects inside features already described as implemented. HD-37–40 and parts
of earlier packages still require acceptance, infrastructure or clinical policy.

The task's six defect groups and Keycloak flow have code fixes or explicit
fail-closed restrictions below. Whole-product readiness and M1–M3 certification
remain unproven. Existing historical evidence must retain its date/revision.

## Changes and regression coverage

### Patient and facility isolation

- New `common/patient_scope.py` centralizes active actor/facility, non-deleted
  patient, self binding and patient/visit checks. A patient-role credential is
  self-bound even if accidentally assigned an additional staff role.
- Forms and immunization no longer accept a guessed patient UUID as sufficient
  authorization. Revoked/unbound patient accounts fail closed. Writes validate
  ownership before catalogue seeding or clinical mutation.
- OT validates the patient, visit and optional admission relationship. Programs
  validate the enrolling patient. Returns validate the patient, supplied
  dispense's prescription owner, and stock batch's item/facility.
- Radiology rejects an attachment item belonging to a different order before
  reading/storing the upload, and bounds the upload read.
- Suite 9 specialty GET/POST previously lacked role dependencies. Reads now
  require doctor/nurse/admin; writes doctor/admin. Both visit and encounter
  facility are checked, as is patient scope. Existing wrong-patient specialty
  rows are not silently reassigned or returned for the correct encounter.
- Tests cover guessed other-patient IDs, revoked binding, foreign facilities,
  wrong visit/dispense/item and nonclinical/mixed-role specialty access. They
  exercise FastAPI dependency chains with synthetic authenticated callers;
  they do not establish a real Keycloak browser session.

### Blood-bank safety and UI contracts

- Crossmatch/issue require available, passed-screening, unexpired units in the
  caller's facility. Issue rechecks after acquiring locks; incompatible,
  previously issued, quarantined/discarded/reserved and pending-screening units
  are refused. Tests mutate state after crossmatch to exercise the issue check.
- Legacy blood tables have no facility column. Scope follows donor.created_by
  to the stored user facility, which the normal user-edit API does not allow
  changing. Unowned rows are excluded. A future historical staff reassignment
  tool must preserve that boundary or introduce immutable native ownership.
- Blood create payloads use actual donor fields, combined ABO/Rh, `bag_number`,
  explicit expiry/screening, and crossmatch `unit_id`. No random bag identifier,
  guessed component or automatic “passed”/“compatible” classification.
- Changing the recipient clears compatibility, notes and immediate-issue
  selection. Old searches are ignored; submission locks the form controls.
  Destination is explicitly stored in issue notes, not an unsupported field.
- Existing eligibility thresholds and the transfusion domain are not newly
  clinically approved. This patch does not implement screening-evidence review,
  full component processing, transfusion monitoring or every retry scenario.

### Immunization

- UI reads `administered`/`due`, sends `vaccine_code`, `administered_at` and
  batch expiry, and renders the actual flat certificate response.
- Backend rejects inactive vaccines, blank batch, future administration and
  expiry preceding administration in the facility timezone. Unknown create
  payload fields are refused instead of silently discarded.
- Certificate UI no longer invents digital-signature/registry verification.
  Patient changes reset modal state; late certificate responses cannot populate
  the new patient's screen.
- Seeded vaccine schedules/doses still require clinical approval; this is not
  a certified national schedule or a digitally signed certificate system.

### Order sets / CSV

- Free-text order protocols have no validated catalogue mapping. Apply now
  returns HTTP 409 `order_set_execution_unavailable`; the modal is preview-only.
  It cannot claim that orders were placed. Individual clinical ordering remains.
- CSV import is limited to real vaccine writes. Required headers/values,
  duplicate columns/codes, dose/age fields, row shape and formula-like cells are
  validated. Unsupported entities fail; the reported imported count reflects
  inserts, not input rows. Existing codes are not silently overwritten.
- To complete order sets: agree/version catalogue mappings and clinical policy,
  use real order writers transactionally, return persistent order IDs, enforce
  idempotency, then test rollback, read-back and downstream worklists. Re-enable
  UI execution only after that. Other entity importers remain unimplemented.

### KPI truthfulness and migration 0081

- OPD wait = visit arrival to first recorded encounter start; missing/negative
  intervals are excluded. Lab TAT = collection to first recorded verify audit
  event; later amendment timestamps cannot inflate it. ED acuity counts recorded
  triage events; IPD admission counts are scoped to this facility's ED visits.
- Missing observations are unavailable, not invented averages or synthetic zero.
  Frontend error paths expose an error rather than fallback dashboard numbers.
- Migration 0081 adds nullable `kpi_snapshots.calculation_version`. Old rows are
  retained and not retroactively labelled trustworthy. Timing rows are returned
  by KPI list/codes only after the producer stamps `recorded_events_v1`.
- Recalculation invalidates timing provenance for the requested period first;
  without observations, old values remain hidden. Tests prove both genuine
  OPD/lab calculations and retention-without-publication of unverified snapshots.
- This does not implement missing historical source observations, historical
  occupancy reconstruction or a complete analytics warehouse. Approved KPI
  definitions/time windows and production performance review remain necessary.

### Consent context

- List/detail/access-history hooks reject late responses and retained refresh
  callbacks, including A → B → A. Prior rows are hidden on the first new-context
  render rather than waiting for effects to clear them.
- A late consent-create response cannot select the old patient's record in the
  new workspace. Mutation UI is keyed by patient/record; unmounted transitions
  cannot show success toasts or update the new workspace.
- Tests execute the actual hooks/components using the repository harness with
  controlled promises. They are not browser, network-throttling or real consent
  operations. Requests legitimately submitted before a switch are not retroactively
  cancelled on the server; their late UI effects are discarded.

### Same-origin native Keycloak login

- Removed the application password form/password grant, manual SDK token-field
  assignment and refresh-token storage/restoration. Native Keycloak handles
  credentials, required actions and MFA via authorization code + PKCE S256.
- Keycloak's public path is served through the current HealthDoc origin, avoiding
  stale built-in LAN hostnames. Same-origin return validation rejects external,
  protocol-relative, credential-bearing, backslash/control-character and auth
  endpoint targets. Original internal path, query and fragment are preserved,
  including after session expiration.
- Existing `hd_rt` local/session-storage values are removed. The realm template
  disables direct grants. Tests assert these boundaries and current-origin
  login options; they do not prove deployment cookies/issuer/MFA configuration.

## Verification

| Gate | Result / meaning |
|---|---|
| Focused backend: security regressions, Suites 6–9, auth policy | **63 passed**; isolated SQLite/API tests, not PostgreSQL row-lock proof |
| Frontend `npm test` | **130 passed, zero skipped** |
| TypeScript `tsc --noEmit --incremental false` | Passed |
| ESLint changed source files | Passed |
| API route matrix | **311 calls valid**; route existence only, not payload correctness |
| Migration integrity | **88 migrations**, linear, downgrade present, head **0081** |
| `alembic upgrade 0080:0081 --sql` | Generated PostgreSQL ALTER successfully; no database mutated |
| Schema drift | 121 documented tables checked; zero blockers/warnings |
| Facility-scope AST/read regression files | 26 passed |
| Blood screening mutation check | Removing the screening guard produced exactly two failures (failed/pending); guard restored, six issue-state cases re-run |
| Final non-ABDM/backend sweep | **939 passed, 346 skipped**; explicit infrastructure exclusions below |
| Convention scripts | Zero blockers; backend idempotency warnings and frontend idempotency/date-format warnings remain; not warning-free |

Broader-run outcomes and limits:

The final broad command, run from `backend` with the project virtualenv, was:

```sh
PYTHONPATH=.:tests python -m pytest -q tests/ \
  --ignore=tests/integrations \
  --ignore=tests/test_backup_restore.py \
  --ignore=tests/test_dev_shutdown.py \
  --ignore=tests/test_queue_sse.py \
  --ignore=tests/test_redis.py --maxfail=5 --tb=short
```

This is deliberately labelled a partial environment-independent gate, not the
full release gate. Restore the excluded suites in the configured test stack.

- The first non-ABDM sweep exposed a stale test requiring password grants; it
  was changed to assert native authorization-code flow with direct grants disabled.
- A later broad non-ABDM run passed **936**, skipped **346**, and failed **three
  Redis tests** because local Redis/socket access was unavailable. It preceded
  the final provenance and specialty changes; do not attribute it to final HEAD.
- The all-backend run hit Java ECDH integration failures: this host has no usable
  Java runtime. Backup tests lack isolated worktree DB configuration; SSE/server
  tests need runtime crypto keys and socket access. These were not weakened.
- Docker daemon was unavailable even with an authorized direct diagnostic.
  Consequently **no real PostgreSQL concurrency, migration apply/restore, full
  browser, or live ABDM acceptance was completed in this pass**. Host `make`
  also encounters an unaccepted Xcode licence; direct test commands were used.

## Deployment and acceptance checklist — still required

1. Review this branch against base `35d8cc4`; merge through staging only after CI
   and human approval. Other agent's source checkout remains unchanged.
2. Start the isolated test stack and configure its database/Redis/crypto keys.
   Install a supported JDK or use the project image for crypto tests. Never
   point destructive fixtures or restore exercises at the development patient DB.
3. Apply **0081 before starting the new backend**. It is additive; do not mark old
   snapshots measured by backfilling its version. Recompute intended periods
   through authorized `/reports/kpis/produce` and verify read-back. Downgrade
   removes provenance and must not be used with the new backend still running.
4. Rebuild frontend/backend. On the **existing** Keycloak frontend client enable
   Standard Flow, require S256 PKCE and disable Direct Access Grants. Preserve
   users, roles and secrets; realm reimport is not a safe way to patch it.
   Verify the same-origin `/auth` proxy, exact allowed redirect/web origins,
   issuer alignment, TLS and the themed Keycloak form.
5. Browser-test deep link → native login → same exact authorized route; logout,
   expired session, silent SSO, required actions/MFA and denied-role paths. No
   passwords/refresh tokens should appear in app storage or evidence.
6. Exercise populated blood/immunization/form/CSV workflows with disposable
   records. Inspect persisted rows, not just toasts. Test expired/failed units,
   wrong-patient/facility IDs, binding revocation, late A responses after B and
   after returning to A. Concurrent PostgreSQL issue attempts must issue once.
7. Fix/review idempotent retries for the new write APIs, especially uncertain
   network outcomes; do not waive warnings merely because happy paths pass.
8. Re-run all-role actions, a11y/keyboard, patient-specific print/PDF, referral
   attachments, tariff/financial reconciliation, security/load and recovery
   acceptance. Obtain clinical/privacy/finance approvals for seeded policies.

## ABDM status and next actions

No milestone certification claim changes here. M1 identity/UI and Scan-and-Share
code exist; M2 HIP and M3 HIU services, FHIR/crypto, jobs, diagnostics and viewers
exist. No fresh genuine NHA/PHR round trip was performed in this review.

- **M1:** reconcile assigned case ledger; test registration/verification and
  applicable card/profile/Scan-and-Share cases with current participant consent
  and private OTP entry. New reception tickets need expiry/duplicate/check-in
  acceptance; presence of a Scan-and-Share tab is not evidence of completion.
- **M2:** resolve the genuine link-token/link-confirmation flow using durable
  receipts/support tracing, then PHR visibility, approved consent, encrypted
  transfer and receipt plus negative cases. The latest owner report says the
  ticket is unanswered; this pass did not inspect the inbox. An approved relay
  is still needed for the alternative mediated OTP flow.
- **M3:** obtain genuine/NHA-approved clinician requester identity and an
  authorized counterparty; execute approval/denial, receive/decrypt/validate/view,
  receipt and revoke/expire/retry scenarios. Save redacted correlated evidence.
- Historical local consent through 14 September is expired. Do not start
  outbound workers, regenerate linking tokens or reuse that authorization
  automatically. NHA assesses certification; synthetic local tests cannot do so.

See also `CLAUDE.md`, `Issues/Agent-Change-Log.md`, the local untracked
`Issues/Updates.md` handoff and the dated ABDM case ledger/runbooks. Preserve
implementer claims as historical records; do not relabel them independent acceptance.
