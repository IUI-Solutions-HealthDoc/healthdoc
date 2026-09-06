# HealthDoc — role functionality verification

## Gate result

All configured gates completed successfully in run `fullcheck-20260906`.

Captured 2026-09-06T07:49:05.989Z against a local development stack at `https://localhost`, signing in through the real Keycloak realm as each role's development account. No API mocking and no direct token grants.

> The screenshots below are build artifacts, not source: `docs/evidence/` is gitignored because each verification run rewrites ~25 MB of images. On GitHub the image links will not render until you regenerate them locally — see `docs/local-role-verification.md` for the commands.

## What a screenshot here means

A screenshot alone does not establish functionality. Each screenshot below was taken **after** the gate judged that screen, and carries that verdict. For a screen to be marked verified, all of the following held while it loaded:

- the role reached the route without being redirected away;
- every `/api/v1` request it made carried a `Bearer` token and succeeded, except exact documented expected responses (such as no appointed DPO);
- every request it started produced a response;
- the page painted no `role="alert"` error state;
- no uncaught browser exception occurred;
- screens expected to read data made at least one API call — a screen wired to nothing renders exactly like a working one.

Screens marked FAIL are shown too, with the reason. They need investigation; they are not passing evidence.

## Scope, and what this does not prove

There are two levels of evidence here, and the difference matters more than the totals.

**Screen level** covers the configured role/sidebar workspace pairs. It proves the screen loads for that role, authenticates, calls its APIs successfully and renders no error. It does **not** prove the screen's buttons do anything.

**Workflow level** entries exercise the specific reads, writes or access checks described below — a service log that survives a reload, a patient admitted to a bed and discharged again, a consultation that closes its queue token, an identity promotion a second supervisor has to approve. A read-only tab check is not evidence that its create or approval controls work.

Suite completion timestamps:

- Dashboards: 2026-09-06T07:49:05.989Z
- Workflows: 2026-09-06T07:30:49.991Z
- Superadmin: 2026-09-06T07:31:27.237Z

What this still does not prove: that *every* control on every screen works. A workflow covers the path it walks. Where a screen offers actions no workflow below exercises — independent lab release, a pharmacist's dispense, an admin creating staff — that screen is verified as loading and reading correctly, and no more than that.

Nothing here involves ABDM sandbox participants, real OTP delivery, or external consent approval; those need counterparties this stack does not have.

## Summary

| Role | Account | Screens verified | Workflow steps verified |
|---|---|---|---|
| Receptionist | `dev.receptionist` | 5/5 | 7/7 |
| Doctor | `dev.doctor` | 10/10 | 7/7 |
| Nurse | `dev.nurse` | 4/4 | 4/4 |
| Lab tech | `dev.labtech` | 2/2 | 3/3 |
| Radiology tech | `dev.radiology` | 2/2 | 2/2 |
| Pharmacist | `dev.pharmacist` | 3/3 | 5/5 |
| Emergency | `dev.emergency` | 1/1 | 1/1 |
| Supervisor | `dev.supervisor` | 2/2 | 4/4 |
| HOD | `dev.hod` | 2/2 | 1/1 |
| Admin | `dev.admin` | 11/11 | 1/1 |
| Auditor | `dev.auditor` | 3/3 | 2/2 |
| Patient | `dev.patient` | 1/1 | 2/2 |
| Superadmin | `dev.superadmin` | 1/1 | 1/1 |
| Public (no sign-in) | not signed in | — | 1/1 |

**47 of 47 screens** and **41 of 41 workflow steps** verified.

## Receptionist

Signed in as `dev.receptionist`.

### Registration — `/receptionist/registration` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![Registration as Receptionist](evidence/roles/receptionist__receptionist-registration.png)

### Patient search — `/receptionist/patient-search` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![Patient search as Receptionist](evidence/roles/receptionist__receptionist-patient-search.png)

### Queue — `/receptionist/queue` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Queue as Receptionist](evidence/roles/receptionist__receptionist-queue.png)

### Billing — `/billing` — PASS

3 of 3 API request(s) answered, none failing; no error state rendered.

![Billing as Receptionist](evidence/roles/receptionist__billing.png)

### Consent — `/consent` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Consent as Receptionist](evidence/roles/receptionist__consent.png)

### Registration — IPD visit for admission (workflow) — PASS

Created the IPD visit the ward admits against. No counter token is issued for an admission.

![Registration — IPD visit for admission](evidence/roles/workflow__receptionist__registration-ipd-visit-for-admission.png)

### Registration — OPD visit and token (workflow) — PASS

Registered a walk-in and issued token `GENMED-005`. Unlike the non-OPD types, an outpatient visit does take a counter token.

![Registration — OPD visit and token](evidence/roles/workflow__receptionist__registration-opd-visit-and-token.png)

### Consent — record clinical review (workflow) — PASS

Recorded a granted `clinical_review` consent for the patient. Without it the doctor's record view stays locked and the only way in is an audited two-hour break-glass override.

![Consent — record clinical review](evidence/roles/workflow__receptionist__consent-record-clinical-review.png)

### Registration — ipd visit (workflow) — PASS

Registered a patient and created a `ipd` visit. The visit persisted against that patient id, no OPD queue token was issued, and no doctor selector was offered — the OPD pipeline no longer runs for every visit type.

![Registration — ipd visit](evidence/roles/workflow__receptionist__registration-ipd-visit.png)

### Registration — day_care visit (workflow) — PASS

Registered a patient and created a `day_care` visit. The visit persisted against that patient id, no OPD queue token was issued, and no doctor selector was offered — the OPD pipeline no longer runs for every visit type.

![Registration — day_care visit](evidence/roles/workflow__receptionist__registration-day-care-visit.png)

### Registration — emergency visit (workflow) — PASS

Registered a patient and created a `emergency` visit. The visit persisted against that patient id, no OPD queue token was issued, and no doctor selector was offered — the OPD pipeline no longer runs for every visit type.

![Registration — emergency visit](evidence/roles/workflow__receptionist__registration-emergency-visit.png)

### Registration — teleconsult visit (workflow) — PASS

Registered a patient and created a `teleconsult` visit. The visit persisted against that patient id, no OPD queue token was issued, and no doctor selector was offered — the OPD pipeline no longer runs for every visit type.

![Registration — teleconsult visit](evidence/roles/workflow__receptionist__registration-teleconsult-visit.png)

## Doctor

Signed in as `dev.doctor`.

### Doctor queue — `/doctor/dashboard` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Doctor queue as Doctor](evidence/roles/doctor__doctor-dashboard.png)

### Consultation — `/doctor/consultation` — PASS

2 of 2 API request(s) answered, none failing; no error state rendered.

![Consultation as Doctor](evidence/roles/doctor__doctor-consultation.png)

### Orders — `/doctor/orders` — PASS

4 of 4 API request(s) answered, none failing; no error state rendered.

![Orders as Doctor](evidence/roles/doctor__doctor-orders.png)

### Prescriptions — `/doctor/prescriptions` — PASS

4 of 4 API request(s) answered, none failing; no error state rendered.

![Prescriptions as Doctor](evidence/roles/doctor__doctor-prescriptions.png)

### Results — `/doctor/results` — PASS

4 of 4 API request(s) answered, none failing; no error state rendered.

![Results as Doctor](evidence/roles/doctor__doctor-results.png)

### Pharmacy approvals — `/doctor/pharmacy-approvals` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Pharmacy approvals as Doctor](evidence/roles/doctor__doctor-pharmacy-approvals.png)

### Laboratory — `/lab` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Laboratory as Doctor](evidence/roles/doctor__lab.png)

### Radiology — `/radiology` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Radiology as Doctor](evidence/roles/doctor__radiology.png)

### IPD — `/ipd` — PASS

10 of 10 API request(s) answered, none failing; no error state rendered.

![IPD as Doctor](evidence/roles/doctor__ipd.png)

### Consent — `/consent` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Consent as Doctor](evidence/roles/doctor__consent.png)

### Doctor queue — the walk-in arrives (workflow) — PASS

Token `GENMED-005` issued at reception appears in the doctor's live queue as Waiting.

![Doctor queue — the walk-in arrives](evidence/roles/workflow__doctor__doctor-queue-the-walk-in-arrives.png)

### Consultation — save the encounter (workflow) — PASS

Recorded a chief complaint and saved the encounter, which is what unlocks vitals, diagnoses, orders and prescriptions on this screen.

![Consultation — save the encounter](evidence/roles/workflow__doctor__consultation-save-the-encounter.png)

### Consultation — place lab order (workflow) — PASS

Created the order header and its department item, then displayed accession LAB-20260906-00005. Synthetic test order only.

![Consultation — place lab order](evidence/roles/workflow__doctor__consultation-place-lab-order.png)

### Consultation — place radiology order (workflow) — PASS

Created the order header and its department item, then displayed accession RAD-20260906-00005. Synthetic test order only.

![Consultation — place radiology order](evidence/roles/workflow__doctor__consultation-place-radiology-order.png)

### Consultation — complete (workflow) — PASS

Closed the encounter. The queue token must close with it.

![Consultation — complete](evidence/roles/workflow__doctor__consultation-complete.png)

### Doctor queue — the token closes with the consultation (workflow) — PASS

After completion, `GENMED-005` is no longer Waiting. This is the regression check for the defect where a completed consultation left its patient in the queue indefinitely.

![Doctor queue — the token closes with the consultation](evidence/roles/workflow__doctor__doctor-queue-the-token-closes-with-the-consultation.png)

### Radiology — draft, sign off, reload report history (workflow) — PASS

The doctor drafted and finalized the synthetic scan, then reloaded both report versions and the DiagnosticReport bundle.

![Radiology — draft, sign off, reload report history](evidence/roles/workflow__doctor__radiology-draft-sign-off-reload-report-history.png)

## Nurse

Signed in as `dev.nurse`.

### Ward dashboard — `/nurse/ward-dashboard` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Ward dashboard as Nurse](evidence/roles/nurse__nurse-ward-dashboard.png)

### eMAR — `/nurse/emar` — PASS

4 of 4 API request(s) answered, none failing; no error state rendered.

![eMAR as Nurse](evidence/roles/nurse__nurse-emar.png)

### IPD — `/ipd` — PASS

9 of 9 API request(s) answered, none failing; no error state rendered.

![IPD as Nurse](evidence/roles/nurse__ipd.png)

### Consent — `/consent` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Consent as Nurse](evidence/roles/nurse__consent.png)

### IPD — admit to a bed (workflow) — PASS

Admitted the patient into bed `B03`, chosen from the vacant beds in that ward. Every nursing screen below is keyed on this admission.

![IPD — admit to a bed](evidence/roles/workflow__nurse__ipd-admit-to-a-bed.png)

### Ward dashboard — the bed resolves to its occupant (workflow) — PASS

Selecting bed `B03` opens the live chart for the patient admitted into it.

![Ward dashboard — the bed resolves to its occupant](evidence/roles/workflow__nurse__ward-dashboard-the-bed-resolves-to-its-occupant.png)

### Ward dashboard — record vitals (workflow) — PASS

Charted a set of observations against the admission and confirmed they appear on the patient's vitals timeline, not merely that the POST returned 201.

![Ward dashboard — record vitals](evidence/roles/workflow__nurse__ward-dashboard-record-vitals.png)

### IPD — discharge and free the bed (workflow) — PASS

Discharged the admission through the two-step preview/confirm flow, returning bed `B03` to the vacant pool.

![IPD — discharge and free the bed](evidence/roles/workflow__nurse__ipd-discharge-and-free-the-bed.png)

## Lab tech

Signed in as `dev.labtech`.

### Laboratory — `/lab` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Laboratory as Lab tech](evidence/roles/lab_tech__lab.png)

### Equipment maintenance — `/admin/maintenance` — PASS

6 of 6 API request(s) answered, none failing; no error state rendered.

![Equipment maintenance as Lab tech](evidence/roles/lab_tech__admin-maintenance.png)

### Equipment maintenance — record service (workflow) — PASS

Created service log `E2E-527aa756`, confirmed it survived a full page reload, filtered to exactly that row, and confirmed unrecorded downtime is stored as null rather than zero.

![Equipment maintenance — record service](evidence/roles/workflow__lab_tech__equipment-maintenance-record-service.png)

### Lab — collect ordered sample (workflow) — PASS

Collected the synthetic doctor's order with a unique barcode; the worklist moved to in progress.

![Lab — collect ordered sample](evidence/roles/workflow__lab_tech__lab-collect-ordered-sample.png)

### Lab — result persists and self-verification is refused (workflow) — PASS

Saved a synthetic preliminary result, received 403 on self-verification, then reloaded its unchanged preliminary history. Independent release still needs a second lab-tech identity.

![Lab — result persists and self-verification is refused](evidence/roles/workflow__lab_tech__lab-result-persists-and-self-verification-is-refused.png)

## Radiology tech

Signed in as `dev.radiology`.

### Radiology — `/radiology` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Radiology as Radiology tech](evidence/roles/radiology_tech__radiology.png)

### Equipment maintenance — `/admin/maintenance` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Equipment maintenance as Radiology tech](evidence/roles/radiology_tech__admin-maintenance.png)

### Equipment maintenance — record service (workflow) — PASS

Created service log `E2E-6a2de294`, confirmed it survived a full page reload, filtered to exactly that row, and confirmed unrecorded downtime is stored as null rather than zero.

![Equipment maintenance — record service](evidence/roles/workflow__radiology_tech__equipment-maintenance-record-service.png)

### Radiology — schedule, reschedule, complete scan (workflow) — PASS

Booked and moved a synthetic scan with a reason, marked it scanned, and verified doctor-only reporting controls are not offered to the technician.

![Radiology — schedule, reschedule, complete scan](evidence/roles/workflow__radiology_tech__radiology-schedule-reschedule-complete-scan.png)

## Pharmacist

Signed in as `dev.pharmacist`.

### Pharmacy queue — `/pharmacy/prescription-queue` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Pharmacy queue as Pharmacist](evidence/roles/pharmacist__pharmacy-prescription-queue.png)

### Dispense — `/pharmacy/dispense` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Dispense as Pharmacist](evidence/roles/pharmacist__pharmacy-dispense.png)

### Inventory — `/inventory` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Inventory as Pharmacist](evidence/roles/pharmacist__inventory.png)

### Inventory — Goods receipt (workflow) — PASS

Tab loaded `GET /pharmacy/grn` with a bearer token and rendered no error state.

![Inventory — Goods receipt](evidence/roles/workflow__pharmacist__inventory-goods-receipt.png)

### Inventory — Transfers (workflow) — PASS

Tab loaded `GET /inventory/stock-transfers` with a bearer token and rendered no error state.

![Inventory — Transfers](evidence/roles/workflow__pharmacist__inventory-transfers.png)

### Inventory — Indents (workflow) — PASS

Tab loaded `GET /pharmacy/indents` with a bearer token and rendered no error state.

![Inventory — Indents](evidence/roles/workflow__pharmacist__inventory-indents.png)

### Inventory — Adjustments (workflow) — PASS

Tab loaded `GET /pharmacy/adjustments` with a bearer token and rendered no error state.

![Inventory — Adjustments](evidence/roles/workflow__pharmacist__inventory-adjustments.png)

### Inventory — approver lookup (workflow) — PASS

Staff search returned a first approver, so an adjustment can actually be routed for maker-checker approval.

![Inventory — approver lookup](evidence/roles/workflow__pharmacist__inventory-approver-lookup.png)

## Emergency

Signed in as `dev.emergency`.

### Emergency — `/emergency` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![Emergency as Emergency](evidence/roles/emergency__emergency.png)

### Emergency — register and issue a THID (workflow) — PASS

Registered an unidentified arrival and issued temporary identity `TH-DEV001-260906-0005`. No name, ABHA or ID is required to get a patient into the system.

![Emergency — register and issue a THID](evidence/roles/workflow__emergency__emergency-register-and-issue-a-thid.png)

## Supervisor

Signed in as `dev.supervisor`.

### Identity merges — `/supervisor/merges` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![Identity merges as Supervisor](evidence/roles/supervisor__supervisor-merges.png)

### Reports — `/reports` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Reports as Supervisor](evidence/roles/supervisor__reports.png)

### Identity merges — request THID→UHID promotion (workflow) — PASS

Raised the promotion request. It stays pending until a different supervisor approves it, which is the whole point of the control.

![Identity merges — request THID→UHID promotion](evidence/roles/workflow__supervisor__identity-merges-request-thid-uhid-promotion.png)

### Identity merges — self-approval is refused (workflow) — PASS

The supervisor who raised the request cannot approve it: the server answered 409. Proving the refusal matters more than proving the happy path.

![Identity merges — self-approval is refused](evidence/roles/workflow__supervisor__identity-merges-self-approval-is-refused.png)

### Identity merges — a second supervisor approves (workflow) — PASS

A different supervisor approved the promotion and the chart was assigned a permanent UHID. The temporary identity `TH-DEV001-260906-0005` is now a real record.

![Identity merges — a second supervisor approves](evidence/roles/workflow__supervisor__identity-merges-a-second-supervisor-approves.png)

### Identity merges — unmerge a wrong promotion (workflow) — PASS

Reversed the promotion, returning the chart to its temporary identity. Unmerge is performed by someone other than the approver.

![Identity merges — unmerge a wrong promotion](evidence/roles/workflow__supervisor__identity-merges-unmerge-a-wrong-promotion.png)

## HOD

Signed in as `dev.hod`.

### Department dashboard — `/hod` — PASS

14 of 14 API request(s) answered, none failing; no error state rendered.

![Department dashboard as HOD](evidence/roles/hod__hod.png)

### Inventory — `/inventory` — PASS

9 of 9 API request(s) answered, none failing; no error state rendered.

![Inventory as HOD](evidence/roles/hod__inventory.png)

### Department roster — add a doctor (workflow) — PASS

Rostered Dev Doctor for today. Reception cannot open an OPD queue until a department head has done this, so this is the first step of the clinical day.

![Department roster — add a doctor](evidence/roles/workflow__hod__department-roster-add-a-doctor.png)

## Admin

Signed in as `dev.admin`.

### Admin overview — `/admin` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![Admin overview as Admin](evidence/roles/admin__admin.png)

### Users — `/admin/users` — PASS

7 of 7 API request(s) answered, none failing; no error state rendered.

![Users as Admin](evidence/roles/admin__admin-users.png)

### Departments & rooms — `/admin/departments` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Departments & rooms as Admin](evidence/roles/admin__admin-departments.png)

### Permissions — `/admin/permissions` — PASS

7 of 7 API request(s) answered, none failing; no error state rendered.

![Permissions as Admin](evidence/roles/admin__admin-permissions.png)

### Account requests — `/admin/account-requests` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Account requests as Admin](evidence/roles/admin__admin-account-requests.png)

### ABDM identity links — `/admin/abdm-sync` — PASS

1 of 1 API request(s) answered, none failing; no error state rendered.

![ABDM identity links as Admin](evidence/roles/admin__admin-abdm-sync.png)

### Audit trail — `/audit-viewer` — PASS

13 of 13 API request(s) answered, none failing; no error state rendered.

![Audit trail as Admin](evidence/roles/admin__audit-viewer.png)

### Data protection — `/admin/data-protection` — PASS

8 of 8 API request(s) answered, none failing; no error state rendered.

![Data protection as Admin](evidence/roles/admin__admin-data-protection.png)

### Equipment maintenance — `/admin/maintenance` — PASS

5 of 5 API request(s) answered, none failing; no error state rendered.

![Equipment maintenance as Admin](evidence/roles/admin__admin-maintenance.png)

### Reports — `/reports` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Reports as Admin](evidence/roles/admin__reports.png)

### Billing — `/billing` — PASS

3 of 3 API request(s) answered, none failing; no error state rendered.

![Billing as Admin](evidence/roles/admin__billing.png)

### Equipment maintenance — record service (workflow) — PASS

Created service log `E2E-9b099fc4`, confirmed it survived a full page reload, filtered to exactly that row, and confirmed unrecorded downtime is stored as null rather than zero.

![Equipment maintenance — record service](evidence/roles/workflow__admin__equipment-maintenance-record-service.png)

## Auditor

Signed in as `dev.auditor`.

### Audit trail — `/audit-viewer` — PASS

13 of 13 API request(s) answered, none failing; no error state rendered.

![Audit trail as Auditor](evidence/roles/auditor__audit-viewer.png)

### Data protection — `/admin/data-protection` — PASS

7 of 7 API request(s) answered, none failing; no error state rendered.

![Data protection as Auditor](evidence/roles/auditor__admin-data-protection.png)

### Reports — `/reports` — PASS

11 of 11 API request(s) answered, none failing; no error state rendered.

![Reports as Auditor](evidence/roles/auditor__reports.png)

### Audit trail — the default view (workflow) — PASS

100 row(s) render before any filter is touched. This view used to open empty until a filter was applied.

![Audit trail — the default view](evidence/roles/workflow__auditor__audit-trail-the-default-view.png)

### Audit trail — filtering narrows the result (workflow) — PASS

Filtering to `admissions` moved the row count from 100 to 17, and still matched rows. A filter wired to nothing renders identically to one that matched everything, so the count has to move and stay non-zero.

![Audit trail — filtering narrows the result](evidence/roles/workflow__auditor__audit-trail-filtering-narrows-the-result.png)

## Patient

Signed in as `dev.patient`.

### My health record — `/patient-portal` — PASS

9 of 9 API request(s) answered, none failing; no error state rendered.

![My health record as Patient](evidence/roles/patient__patient-portal.png)

### My health record — own chart and access history (workflow) — PASS

The portal loaded this patient's own record, ABHA link status and data-access history with no failing call. Every read here is scoped to the signed-in patient by the server.

![My health record — own chart and access history](evidence/roles/workflow__patient__my-health-record-own-chart-and-access-history.png)

### Patient portal — staff routes are refused at the API (workflow) — PASS

With this patient's own token, `GET /api/v1/audit/logs`, `GET /api/v1/queue/worklist`, `POST /api/v1/patients/search` all answered 403. The sidebar hiding them is containment, not authorisation.

![Patient portal — staff routes are refused at the API](evidence/roles/workflow__patient__patient-portal-staff-routes-are-refused-at-the-api.png)

## Superadmin

Signed in as `dev.superadmin`.

### Facilities — `/superadmin` — PASS

3 of 3 API request(s) answered, none failing; no error state rendered.

![Facilities as Superadmin](evidence/roles/superadmin__superadmin.png)

### Platform isolation — permitted, denied and redirected (workflow) — PASS

Signed in as dev.superadmin and landed on /superadmin. The permitted platform read answered 200; every facility and clinical route answered 403 to this role's own bearer token; and every facility workspace redirected away. The API check is the one that counts — a hidden menu stops a confused operator and does nothing about curl.

![Platform isolation — permitted, denied and redirected](evidence/roles/workflow__superadmin__platform-isolation.png)

## Public (no sign-in)

No workspace of its own — this is functionality that belongs to no signed-in role.

### Queue display — corridor wall screen (workflow) — PASS

Opened `/queue-display` in a browser with no session, reached the board without a login redirect, and the department stream went `Live` over a request carrying no Authorization header.

![Queue display — corridor wall screen](evidence/roles/workflow__public__queue-display-corridor-wall-screen.png)

