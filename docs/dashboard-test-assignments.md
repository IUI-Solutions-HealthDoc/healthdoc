# Dashboard manual-test assignments

This checklist is generated from the current role route and dashboard smoke
matrices. It contains **34 distinct workspaces and 47 role/workspace
assignments**. Shared screens are intentionally repeated because authorization
and available actions must be verified independently for every role.

All accounts below are development identities only. The local development
password is `devpass`.

## Evidence required from every assignee

For every assigned route:

- Record the route, browser, result, and a screenshot.
- Confirm only the menus listed for that role appear in the sidebar.
- On desktop, confirm opening the sidebar shifts the screen right and does not
  cover it. On mobile, confirm it overlays and closes with Escape/outside click.
- Keep DevTools Network filtered to `/api/v1`; every API request must carry a
  bearer token and no unexpected request may return 4xx/5xx.
- Submit each form once with invalid data. It must show an inline, readable
  validation message and must not send an API request.
- Force or record an API failure. The toast must be readable and must not show
  raw JSON, a Pydantic array, stack text, or internal identifiers.
- Exercise the primary action, not only page loading, and verify the saved
  result after refresh.
- Verify an unauthorized route redirects to the role's landing page.

The only allowed dashboard response exception is `GET /api/v1/dpdp/dpo` = 404
when the facility has not appointed a DPO. The page must explain that state.

## Assignment 1 — Receptionist

Account: `dev.receptionist`

Landing page: `/receptionist/registration`

Forbidden-route check: `/admin`

- [ ] `/receptionist/registration` — duplicate search with name + DOB; then
  register a new patient and verify the resulting identity.
- [ ] `/receptionist/patient-search` — test name + DOB, mobile, UHID and ABHA
  searches, including invalid mobile/ABHA values.
- [ ] `/receptionist/queue` — create/start a visit and verify its queue token.
- [ ] `/billing` — inspect an invoice and exercise the permitted payment flow.
- [ ] `/consent` — select a patient and verify consent records load.

## Assignment 2 — Doctor

Account: `dev.doctor`

Landing page: `/doctor/dashboard`

Forbidden-route check: `/admin`

- [ ] `/doctor/dashboard` — open a patient from the live worklist.
- [ ] `/doctor/consultation` — open through the queue, save clinical data and
  verify it survives refresh.
- [ ] `/doctor/orders` — create a lab and radiology order.
- [ ] `/doctor/prescriptions` — create and review a prescription.
- [ ] `/doctor/results` — inspect live results and result status.
- [ ] `/doctor/pharmacy-approvals` — complete a dual-approval action.
- [ ] `/lab` — verify doctor-visible pathology data and actions.
- [ ] `/radiology` — verify doctor-visible imaging data and reports.
- [ ] `/ipd` — inspect admissions and the clinical IPD workspace.
- [ ] `/consent` — select a patient and verify consent records load.

## Assignment 3 — Nurse

Account: `dev.nurse`

Landing page: `/nurse/ward-dashboard`

Forbidden-route check: `/admin`

- [ ] `/nurse/ward-dashboard` — verify beds, admission, tasks and live patient
  data.
- [ ] `/nurse/emar` — record a medication administration and verify history.
- [ ] `/ipd` — inspect the admission, observations and nursing actions.
- [ ] `/consent` — select a patient and verify consent records load.

## Assignment 4 — Laboratory technician

Account: `dev.labtech`

Landing page: `/lab`

Forbidden-route check: `/admin`

- [ ] `/lab` — receive a sample, enter a result and complete verification.
- [ ] `/admin/maintenance` — add a laboratory machine maintenance record;
  blank downtime must remain “not recorded”, never zero.

## Assignment 5 — Radiology technician

Account: `dev.radiology`

Landing page: `/radiology`

Forbidden-route check: `/admin`

- [ ] `/radiology` — schedule/acquire a study, enter findings and verify its
  report workflow.
- [ ] `/admin/maintenance` — add an imaging-machine maintenance record;
  blank downtime must remain “not recorded”, never zero.

## Assignment 6 — Pharmacist

Account: `dev.pharmacist`

Landing page: `/pharmacy/prescription-queue`

Forbidden-route check: `/admin`

- [ ] `/pharmacy/prescription-queue` — open a live prescription and verify its
  approval/dispensing state.
- [ ] `/pharmacy/dispense` — dispense against actual batches and verify stock
  and partial-quantity behaviour.
- [ ] `/inventory` — test all five tabs, including receiving/GRN, indents,
  adjustments, reorder alerts and expiry tracking.

## Assignment 7 — Emergency registrar

Account: `dev.emergency`

Landing page: `/emergency`

Forbidden-route check: `/admin`

- [ ] `/emergency` — create a temporary emergency identity and verify required
  fields, optional fields and the returned identifier.

## Assignment 8 — Records supervisor

Account: `dev.supervisor`

Landing page: `/supervisor/merges`

Forbidden-route check: `/admin`

- [ ] `/supervisor/merges` — exercise merge lookup, merge audit lookup and
  unmerge validation/actions.
- [ ] `/reports` — test presets, a valid custom range, an invalid reversed
  range, refresh and print/PDF.

## Assignment 9 — Head of department

Account: `dev.hod`

Landing page: `/hod`

Forbidden-route check: `/admin`

- [ ] `/hod` — verify department KPIs, staff/roster, queues and pending work.
- [ ] `/inventory` — approve/reject an indent and verify the status change.

## Assignment 10 — Facility administrator

Account: `dev.admin`

Landing page: `/admin`

Forbidden-route check: `/doctor`

- [ ] `/admin` — verify every admin workspace card and link.
- [ ] `/admin/users` — create/edit/deactivate staff; test username, mobile,
  email, role and department validation.
- [ ] `/admin/account-requests` — verify maker-checker self-approval blocking,
  approve with password and reject with a reason.
- [ ] `/admin/permissions` — change a facility module only after entering a
  reason and verify the resulting role matrix.
- [ ] `/admin/departments` — create/edit departments and rooms and verify
  collapsed create forms and validation.
- [ ] `/admin/abdm-sync` — search a patient identity and verify link/unlink
  behaviour.
- [ ] `/audit-viewer` — filter and inspect audit events without mock actions.
- [ ] `/admin/data-protection` — appoint a DPO, create/progress a grievance and
  verify consent-manager governance.
- [ ] `/admin/maintenance` — add and inspect a maintenance record.
- [ ] `/reports` — test presets, custom dates and print/PDF.
- [ ] `/billing` — inspect invoices, permitted payment actions and failures.

Admin must not see or open `/hod`; that workspace belongs to the HOD role.

## Assignment 11 — Auditor

Account: `dev.auditor`

Landing page: `/audit-viewer`

Forbidden-route check: `/admin/users`

- [ ] `/audit-viewer` — filter and inspect audit events.
- [ ] `/admin/data-protection` — verify governance access without access to the
  staff directory.
- [ ] `/reports` — test filters, custom dates and print/PDF.

## Assignment 12 — Patient

Account: `dev.patient`

Landing page: `/patient-portal`

Forbidden-route check: `/doctor`

- [ ] `/patient-portal` — verify the bound patient identity, consents and
  health-data access history; confirm no other patient's data is reachable.

## Assignment 13 — Platform superadmin

Account: `dev.superadmin`

Landing page: `/superadmin`

Forbidden-route checks: `/admin`, `/hod`, `/patient-portal`

- [ ] `/superadmin` — load and search the registered-facility directory and
  verify that no facility clinical data or facility-admin menu is exposed.

Superadmin must not land on the removed `/workspace-unavailable` route and must
not be downgraded to facility admin when its token also contains realm-admin.

## Completion report format

Each assignee should return:

| Role | Route | Browser | Primary action | API status | Validation | Toast safety | Sidebar/layout | Result | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Example | `/route` | Chrome | Saved record | 200 | Pass | Pass | Pass | Pass | screenshot/link |

Any failure must include the exact route, test account, timestamp, request
method/path/status, screenshot and reproducible steps. Do not include access
tokens, cookies, patient data or secrets in the report.
