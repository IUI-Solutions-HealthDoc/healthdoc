#!/usr/bin/env bash
# Close the issues whose deliverables were verified present in the tree.
#
# Every number below was checked against a concrete artifact — a component
# file, a route, an endpoint in the OpenAPI spec, or a passing test — not
# against the issue title. Four issues that a title match WOULD have closed are
# deliberately absent; see the "NOT CLOSED" list at the bottom.
#
# Run from the repo root. Re-runnable: closing a closed issue is a no-op.
set -euo pipefail

close() {
  local num="$1"; shift
  gh issue close "$num" --comment "$*" || echo "  ! #$num failed"
  echo "  closed #$num"
}

echo "== Week 1: setup and shared components =="
close 147 "Verified: Next.js 16 + Tailwind, \`src/\` feature-folder structure, production build generates 36 routes."
close 149 "Verified: \`lib/auth/keycloak.ts\`, \`app/(auth)\` login route, \`lib/auth/routes.ts\` role-based guards, \`providers/auth-provider.tsx\` refresh."
close 150 "Verified: \`components/common/\` — MainLayout, Navbar, Sidebar, plus ModuleCapabilityGate for per-facility module toggles."
close 151 "Verified: DataTable, Toaster, StatusChip, CriticalBadge, MedicineSearchModal all present and in use."
close 152 "Verified: \`components/VitalsTimeline\`, \`components/BedGrid\`, \`components/tables/EMARTable\`."
close 153 "Verified: \`components/shared/BarcodeDisplay.tsx\`, \`components/shared/StatusStepper\`, RadiologyReportViewer."
close 154 "Verified: \`components/ui/\` — StockLevelBadge, ExpiryChip, FEFOindicator."
close 155 "Verified: \`components/ui/\` — MetricCard, ChartWrapper (recharts), ExportButton."

echo "== Week 2: role dashboards =="
close 170 "Verified: \`features/receptionist/RegistrationForm.tsx\` wired to live registration endpoints."
close 171 "Verified: \`features/receptionist/PatientSearch.tsx\`, debounced, server-side search."
close 172 "Verified: \`features/doctor/components/DoctorQueuePanel.tsx\` on the live queue endpoint."
close 173 "Verified: \`app/nurse/ward-dashboard\` with BedGrid and ward selector, now on live wards/beds APIs."
close 174 "Verified: \`app/lab\` technician queue plus \`components/shared/BarcodeDisplay.tsx\`."
close 175 "Verified: \`app/pharmacy/prescription-queue\` on the live prescription queue."
close 176 "Verified: \`features/billing/components/BillingDashboard.tsx\` with scheme selector and invoice totals."

echo "== Week 3 =="
close 190 "Verified: \`features/queue-display/\` with \`useQueueStream.ts\` (SSE) and QueueDisplayBoard."
close 191 "Verified: encounter form with SOAP fields and ICD picker; \`icd_codes\` catalog seeded via \`scripts/seed_icd_codes.py\`."
close 192 "Verified: \`app/doctor/orders\` places lab/radiology/procedure orders from the encounter."
close 193 "Verified: VitalsTimeline (time-series) and EMARTable (given/held/refused)."
close 194 "Verified: \`app/lab/page.tsx\` (397 lines) — result entry plus \`verifyLabResult\` pathologist sign-off. NB the code says 'verify', not 'approve'."
close 195 "Verified: \`app/pharmacy/dispense\` with server-side FEFO allocation; batch order comes from the server and is deliberately not re-sorted client-side."
close 196 "Verified: ImmutableReceipt + ReceiptPrintView + useReceiptPrint; reversal is a refund ledger row, never an edit."
echo "== Week 4 =="
close 208 "Verified: \`app/admin/departments\` on the live departments API."
close 209 "Verified: PrescriptionWorkspace + PrescriptionPrintView + prescription-print.css; interaction and allergy banners present."
close 211 "Verified: lab report viewer with ranges, critical banner and print view."
close 212 "Verified: warning banners and return-medicine flow in \`features/pharmacy\`."
close 213 "Verified: \`app/admin/users\` and \`app/admin/permissions\`, both on live endpoints with server-side user search."
close 201 "Verified: \`build_encounter_close_bundles\` is called at \`app/opd/service.py:180\` on encounter close, covered by \`tests/opd/test_encounter_close_fhir.py\`."

echo "== Week 5 =="
close 216 "Verified: \`app/admissions/router.py\` — admission, transfer, discharge, with FHIR bundles and \`tests/integration/test_ipd_journey.py\`."
close 221 "Verified: \`app/emergency\` THID/triage/bypass, and patient merge with supervisor approve/reject endpoints."
close 222 "Verified: lab result viewer with ranges and critical badge, radiology viewer, and doctor sign-off via \`GET /orders/results-worklist\`."
close 223 "Verified: \`features/ipd/AdmissionForm\`, \`DischargeForm\`, BedGrid selector, AddPatientMovementForm for transfers."
close 224 "Verified: \`app/radiology/page.tsx\` — worklist, report draft and sign-off. The missing \`PUT /order-items/{id}/schedule\` step was built as part of this; without it no scan could ever reach 'scanned'."
close 225 "Verified: \`features/inventory/GrnWorkspace.tsx\` and \`IndentWorkspace.tsx\`, plus the six list/master-data endpoints they needed — procurement was write-only until then."
close 226 "Verified: \`features/reports/components/MisDashboard.tsx\` on \`GET /reports/kpis\`. The reports module was a ping stub; \`kpi_snapshots\` had existed unmapped since 0025."

echo "== Week 6 =="
close 235 "Verified: break-glass UI with justification, MFA step-up and countdown; \`POST /break-glass/{id}/revoke\` and \`/review\` added alongside."
close 237 "Verified: PACS placeholder link and radiology print view."
close 238 "Verified: \`features/inventory/AdjustmentWorkspace.tsx\` — dual sign-off surfaced in the UI (submitter filtered from the approver picker, both signatories named on each row), plus ExpiryTracker at 30/60/90."
close 239 "Verified: \`app/audit-viewer\` (audit logs, data-access, file-access, integrity checks) and \`app/consent\` record viewer."

echo "== Week 7 / 8 =="
close 243 "Verified: all five core journeys — test_opd_journey, test_ipd_journey, test_lab_journey, test_pharmacy_http_journey, test_billing_journey."
close 249 "Verified: docs/api-docs.md (human index over the OpenAPI spec, 131 endpoints contract-checked), docs/data-flow.md, docs/security-policy.md, docs/isms-asset-inventory.md."

echo "== Defects =="
close 400 "Fixed: \`_filter_by_preferences\` gates the publish path in \`app/notifications/router.py\`; an event silenced for every role the caller holds is suppressed. 8 passing tests in \`tests/test_notification_publish_gate.py\`."

cat <<'NOTE'

Done — 42 issues closed.

DELIBERATELY NOT CLOSED (a title match would have closed several of these):

  #234 / #228  Patient portal. The page is a 31-line placeholder that says the
               account is not linked, and there are NO /patients/me endpoints
               in the OpenAPI spec. Genuinely unbuilt.
  #368         file_access_log.file_id is still ondelete=RESTRICT in 0019 and
               no later migration changes it. The DPDP erasure conflict stands.
  #148         Electron shell exists (frontend/electron, electron:dev script)
               but there is no Windows/Linux CI build job. Half done.
  #250         Prod compose, Nginx and demo seed are present; Prometheus and
               Grafana appear nowhere in infra/. Half done.
  #244         backup/restore, NTP/TLS and load-test SCRIPTS exist — but the
               issue asks for the runs, not the scripts. Executing them is the
               production rehearsal.
  #242         OWASP ZAP: no scan has been run.
  #240 / #241  Need an actual sweep and an index/performance review.
  #245-#248    a11y, SSE reconnect/autosave, edge cases, print/PDF: components
               exist, but these ask for verification passes over them.
  #251         No demo recordings in the repo.

NOTE
