# HealthDoc — remaining work, 10 September 2026

## Status and evidence boundary

The core HMIS is substantially implemented, but it is **not yet a fully accepted
production release or ABDM-certified product**. A percentage would be misleading:
the comparison backlog mixes defects, missing workflows, external certification,
deployment tests and optional Bahmni-scale products.

GitHub checked today: staging `48dd47d` contains tariff safety (#547); main
`56e079b` contains its staging promotion (#548). There were zero open GitHub
issues or PRs before this session. That empty issue list does not close the
untracked work below. Referral code is now committed (`45fa36d`), integrated
with staging (`ae824a9`) and published in
[PR #549 → staging](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/549).
It was created as draft, subsequently marked ready outside this session, and
has four active CI checks passing. **Its browser acceptance is still blocked.**
This session does not merge to staging or main or deploy production.

This is a status reconciliation against current source and the 9 September
[full functional handoff](healthdoc-vs-bahmni-functional-gap-and-frontend-handoff-2026-09-09.md),
not a fresh exhaustive execution of every hospital workflow. Its F/A/H/O IDs
remain the detailed specifications and acceptance criteria. Older reports with
"everything done", "code-ready" or historical test counts are not current proof.

Fresh publication checks: **1,573 backend + 14 script tests passed**; the local
real-Keycloak role sweep passed **50/51 screens** (admin data-protection timeout).
The separate admin retry passed **12/12**, including that page; this establishes
successful loads across all listed screens, not an entirely clean single sweep.
The referral UI fault test still fails on a React render-depth error while typing
the summary, although its seven workflow assertions pass. Visible Chrome opened
the actual doctor results list and empty referral inbox after a transient 502
reload. Those checks do not prove all actions, uploads or ABDM round trips.

## Built — do not rebuild

- Keycloak login, role containment and scoped backend permissions; patient
  registration/search, OPD queues/consultations, IPD admissions/discharges,
  vitals, orders, prescriptions and pharmacy dispensing.
- Lab worklist/results/verification/amendments/MIS and radiology scheduling,
  cancellation/rescheduling, reporting/versioning/PACS UID fields.
- Separated billing routes/authority, payments/refunds/MIS, effective-dated
  tariffs, automatic departmental tariff resolution, patient/invoice-switch
  protections, and tariff concurrency/idempotency fixes merged through main.
- Inventory/procurement/GRN/indents/transfers/adjustments, HOD, maintenance,
  governance and audit screens. Their presence is not blanket action acceptance.
- Verified patient-portal identity binding and consent/access-history views.
- ABDM v3 wire calls/callbacks; exact finalized-document care contexts; HIP
  linking; durable jobs, encrypted transfer pages and protected HIU storage;
  doctor ABDM workspace/admin jobs; preview-first historical registration tooling.
  These are implementation assets, not completed live milestones.
- PR #549 adds cross-visit referral inbox, outside-result intake/history,
  patient isolation, attachments and public HTTPS storage signing support.
  [Its report](external-referral-results-2026-09-10.md) records incomplete acceptance.

## Ranked release and implementation backlog

| Priority / work | What remains | Closure evidence / dependency |
|---|---|---|
| **P0 — current change acceptance (F04)** | Diagnose prior React render-depth error; test inbox, uploads, receipt retry and downloads in the browser; persist specific referred test/study descriptions; reconcile unknown uploads. | Repeated clean browser runs plus synthetic PostgreSQL/MinIO journey; public storage hostname/TLS/region. Summary-only intake is not a locally verified clinical report. |
| **P0 — M1 identity continuation (A01–A04)** | Separate credential purpose/expiry and secure continuation state; mobile OTP continuation; ABHA address selection/creation; persistent Scan-and-Share reception tickets. Profile/card only if assigned. | Required creation/existing-ABHA cases, wrong/expired OTP, retries, patient switch, correct local binding and the same ticket at reception/PHR. Actual participant/OTP required for external proof. |
| **P0 — remaining M2/M3 reliability (A05/A06/A09/A10)** | Durable discovery/link/profile replies and missing-callback timeout recovery; clinical sign-off/version/author rules; remove active legacy plaintext clinical outbox producers safely; historical cleanup and revocation/receiver races. | Process-crash/timeout/retry tests, actual workflow-generated FHIR validation, correct source authors, no new unprotected clinical payloads, restore cannot revive revoked access. Clinical/retention decisions required. |
| **P0 — live ABDM acceptance (A08/A11/A12)** | Approved callback ingress and registry mapping; OTP relay; controlled worker activation; approved history manifests; independent HIP/HIU/PHR M1–M3 runs and redacted case evidence. | Assigned NHA checklist, consenting sandbox participant, counterpart, verified identities and clinical approval. No certification claim from local mocks or CI alone. |
| **P0 before nursing use — eMAR (F03)** | Administration writer UI; action idempotency and duplicate scheduled-dose protection; held/refused/correction handling. | Clinical approval of dose identity/scheduling first; two-nurse concurrent/retry/maker-checker/patient ownership tests. Do not infer schedules from free-text frequencies. |
| **P0/P1 — laboratory safety (H01/H02)** | Structured analyte/panel forms and approved/versioned ranges; replace process-local critical-alert delivery with shared durable delivery; acknowledgement/escalation workflow. | Lab-approved catalogue/critical rules, cross-process and reconnect tests, no alert before commit, authorized recipients and an agreed escalation owner. |
| **P1 — usable outside records (A07)** | HIU type-specific clinical viewer, patient-chart navigation and clearer asynchronous states. | Read-only prescriptions/results/consultations/discharges with provenance; inert untrusted HTML, no automatic imports/downloads, revocation/expiry and wrong-patient tests. |
| **P1 — hospital completeness (H03/H08/H09)** | KPI producers and publication/revision lifecycle; complete action acceptance of partial stock receipts/transfers/returns; approved IPD bed-day/procedure/blood accrual and scheme/claims scope. | Reconciled source-to-report/stock/bill figures, idempotent retries and independent approvals. PM-JAY eligibility remains a stub, not verified eligibility. |
| **P1/P2 — patient documents and imaging (H04/H05)** | Self-scoped released clinical documents in portal; actual PACS archive-to-authorized-viewer journey. | Release/guardian/sensitive-document policy; real image infrastructure, patient/accession binding, archive recovery and file authorization. |
| **P0/P1 — operations (O01/O02)** | Production-derived migration/restore rehearsal; complete PostgreSQL/Mongo/MinIO/Keycloak/keys recovery and PITR/RPO/RTO decisions; working alert receivers; current authenticated load/security assessment; retention/governance execution. | Actual restored usable/decryptable records, monitored jobs and received alerts, dated test reports and sign-offs. A previous local-copy rehearsal is not production recovery proof. |
| **P1/P2 — quality/release (H12/O03)** | Updated role **action** matrix; print/PDF/labels, keyboard/mobile/zoom review; eliminate stale status claims; stage soak and controlled promotion. | Tested deployed revision, no hidden role/write failures, correct printed values, review/CI/rollback plan. Screen counts do not prove every button. |

Current source spot-checks still show: ambiguous M1 `linking_token` storage;
Scan-and-Share token derived from the UHID rather than a persisted reception
ticket; `payload=bundle` in legacy FHIR outbox producers; no eMAR frontend POST
caller; one placeholder haemoglobin threshold; process-local alert queues;
KPI snapshot readers without the documented producer. These are code gaps,
not merely requests to rerun tests.

## Optional breadth — decide release scope first

H06–H11 include configurable specialty forms, richer longitudinal charts,
appointments/teleconsultation, deeper warehouse/accounting functionality,
terminology/decision-support integration, OT, immunization and blood bank.
These are separate product workstreams, not final dashboard polish. Additional
ABDM HI types (ImmunizationRecord, HealthDocumentRecord, Invoice) should follow
the assigned checklist and real clinical source workflows, not guessed records.

## Practical sequence

1. Finish #549 acceptance and reviewed staging integration. Keep runtime or
   storage configuration failures visible, not waived to get a green label.
2. Implement A01–A04 as one coherent M1 lifecycle. In parallel organizational
   work, obtain the checklist, participant, SMS relay and ingress/registry approval.
3. Close remaining callback recovery and plaintext outbox paths; agree clinical
   signing/version semantics and validate actual generated bundles.
4. Build clinically governed eMAR and structured lab/durable alert workflows.
   Complete agreed bill/KPI sources and portal/PACS scope after those boundaries.
5. Run M1, then M2, then M3 with external counterparts; gather case-by-case
   evidence. Run production recovery/security/load/UAT gates separately.

This is **weeks of implementation plus external approvals**, not a credible
one-day finish. The detailed handoff gives engineering-day ranges per package;
they are estimates, not certification dates. Freeze the must-ship scope and
assign named clinical, finance, operations and integration owners before
promising a release date. Do not count optional Bahmni parity as a small residual
percentage of the existing HMIS.
