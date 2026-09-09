# Local role verification

The earlier generated browser report is
**[role-verification-evidence.md](role-verification-evidence.md)**.
The newer **6–7 September billing/ABDM retest**, including failed development
runs and the separate production-frontend preview, is tracked in
**[billing-abdm-readiness-2026-09-06.md](billing-abdm-readiness-2026-09-06.md)**.
Its evidence uses a separate directory so it cannot silently overwrite the older
run. This file records how evidence is produced and the limits of its coverage.

The **9 September billing-tariff/patient-switch acceptance** is tracked in
[its dated report](billing-patient-safety-browser-acceptance-2026-09-09.md),
with separate evidence, newly reproduced defects and explicit coverage limits.

## Producing it

```bash
make up
cd frontend
# Use a NEW identifier for each complete sweep, shared by these three suites.
export E2E_RUN_ID=your-unique-retest-id
export E2E_ALLOW_RECOVERY=0
E2E_EVIDENCE_DIR=../docs/evidence/roles npm run test:dashboards
E2E_ALLOW_MUTATIONS=1 E2E_EVIDENCE_DIR=../docs/evidence/roles npm run test:workflows
E2E_EVIDENCE_DIR=../docs/evidence/roles npm run test:superadmin
cd .. && python3 scripts/build_role_evidence.py
python3 -m unittest discover -s scripts/tests -p test_role_evidence.py -v
```

If a run fails part-way it can leave a patient admitted, and after a few of
those the ward is full and later runs fail at "no vacant bed" — which looks
like a defect and is not one. Free them with:

```bash
docker compose -f infra/docker-compose.yml exec -e PYTHONPATH=/code backend \
    python /scripts/maintenance/discharge_synthetic_admissions.py
```

The harnesses take screenshots after the relevant assertions and store their
verdicts in JSON beside the images. A workflow can still fail after an earlier
successful screenshot: the suite-level outcomes therefore determine the gate,
not the number of screenshots. The report fails closed on missing suites,
partial runs, missing planned outcomes, failures and mismatched run IDs. Each
suite invalidates its previous manifest before it starts.
Automatic reload/retry is **off by default**. `E2E_ALLOW_RECOVERY=1` opts in for
diagnosis only; any such recovery is recorded as a warning, not clean first-load
evidence. Do not use a recovered run as a release sign-off.

The September retest found real nginx rate limiting, not just Next.js
contention: read-only Keycloak theme assets spent the credential bucket and
two login submissions were refused. The proxy now excludes only GET/HEAD
`/auth/resources/` assets from that bucket, preserving the credential/token
rate and burst limits. A Keycloak 4xx/5xx login response now fails the workflow
immediately rather than being mislabeled as a hydration timeout.

`E2E_ALLOW_MUTATIONS=1` is mandatory for the
workflow run and asserts a localhost base URL: it creates real patients,
visits, consents, encounters and service logs. Never point it at production.

Run the PostgreSQL test gate **before**, not concurrently with, the browser
suites. Shared runtime contention can produce timeouts that are not product
failures. The workflow suite is safe to re-run against the same stack. It rosters,
opens queues and records consent only where those are missing, and tolerates
the 409 that means a previous run already did the work.

## What the evidence covers

Screen level, every configured role/workspace pair: the screen loads,
authenticates, calls its APIs successfully and paints no error. Workflow entries
describe their exact assertion: some write and read back, others check a
read-only tab or an access refusal. They are not interchangeable.

Two of those workflows needed something the stack did not previously have.
The nurse's screens are all keyed on an admitted inpatient, so
`ipd_and_nursing` first registers an IPD visit, admits into a vacant bed,
charts observations, and discharges again — which also returns the bed, so the
suite is safe to re-run. And THID→UHID promotion is maker-checker, so
`dev.supervisor2` was added to the seed: with one supervisor the only
reachable outcome was the refusal, and the approve and unmerge halves of the
flow had never been run by anyone.

The OPD workflow now includes doctor lab/radiology orders, sample collection,
preliminary lab results and self-verification refusal. Radiology covers
scheduling, rescheduling, scan completion, doctor drafting/sign-off and report
history after reload. Doctors must see read-only lab controls and technicians
must not see doctor-only radiology reporting actions.

What is still not covered is every control on every screen. A workflow proves
the path it walks; independent lab release needs a second lab-tech identity.
A pharmacist's dispense, inventory approval chains, staff
creation, full nursing eMAR/fluid-balance actions and exhaustive edge cases are
not established by this suite. Billing now has a real synthetic workflow for
build/issue/payment/admin refund and role refusals; see the dated retest for its
actual outcome, not just the existence of the test. The nursing workflow also
includes SBAR handover creation/read-back; this is not every handover edge case.

## Retest fixes and checks — 5–6 September 2026

- Login: separated read-only Keycloak assets from the credential rate-limit
  bucket. Strict workflow and screen runs completed without recovery; no
  subsequent proxy rate-limit refusals were observed during those runs.
- Radiology: carried the saved machine into the reschedule form. Matched
  technician/doctor action visibility to the existing API role boundaries.
- Lab: doctors retain read access but no longer see technician-only mutations.
  Preliminary results persist after reload; self-verification remains denied.
- Stock adjustments: the write path now rejects inactive, missing and
  cross-facility first-approver nominees, rather than trusting the picker.
  All three cases were reproduced before fixing the service.
- Evidence: failed final assertions, filtered runs, missing outcomes, stale
  manifests and generator crashes cannot silently preserve a passing report.
  Fixed root-redirect and response-body races in the browser harness.
- Source gates: 1,226 backend tests, 23 frontend tests, 11 evidence-report tests;
  193 API contracts; TypeScript and ESLint pass. Backend and production
  frontend dependency audits report no known vulnerabilities.
- Additional browser checks: nine authentication/accessibility/keyboard gates
  pass (no serious/critical Axe findings on those tested states). Four
  print-style smoke cases generate PDFs from synthetic markup. These are not
  exhaustive accessibility or real clinical-document print sign-offs.
- Production compilation and image assembly passed using the Dockerfile's
  actual `prod` target, tagged locally as `healthdoc-frontend:role-retest`.
  The host's Turbopack attempt was blocked while binding an internal port;
  no CSS or application workaround was needed. Development Compose targets
  `dev`, so `make setup` alone is not a production-build check. Nothing was
  deployed or switched to the production image.

To repeat the production build with the same local, public configuration:

```bash
docker build --target prod \
  --build-arg NEXT_PUBLIC_API_BASE_URL=/api/v1 \
  --build-arg NEXT_PUBLIC_KEYCLOAK_URL=/auth \
  -t healthdoc-frontend:role-retest frontend
```

Four existing Pydantic alias warnings in ABDM contract collection remain;
passing local tests are not an ABDM sandbox round trip or certification.

## What it cannot cover

Real ABDM OTP delivery, external consent approval and NHA milestone acceptance
need sandbox counterparties. They are not simulated here and no local run
should be read as evidence for them.
