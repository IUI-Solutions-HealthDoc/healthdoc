# Control room (state / district monitoring) — design

Date: 10 October 2026. Status: slices 1–6 built (PRs #676–#681, stacked); slice 7 waits for DPO approval.
Context: the BHAVYA comparison (`docs/BHAVYA-vs-HealthDoc-comparison-2026-10-09.docx`)
found that HealthDoc has per-facility KPIs but no view across hospitals.

## Decisions (owner, 9–10 Oct)

| Question | Decision |
|---|---|
| Who opens it | New realm role `monitor`. Each monitor has a scope: a whole state, or named districts. A monitor sees only facilities inside the scope. |
| Freshness | Snapshots every 15 minutes, stored per facility. The board reads snapshots, never the clinical tables. |
| First content | Hospital status board, bed availability, stock-out alerts, disease trends, equipment working or not, doctor availability with cover, and a facility activity drill-down (first/last patient, medicines given, procedures, which staff). |

## Privacy rule (the decision that is hard to undo)

A monitor is not part of any patient's care. DPDP and the existing HealthDoc
conventions (facility isolation, audit opt-in, superadmin "never clinical data")
therefore apply as follows:

1. **Board, beds, stock, trends, equipment, staff**: aggregates and facility
   facts only. No patient identifiers. Disease trends suppress cells below 5
   patients so a rare diagnosis in a small block cannot identify a person.
2. **Activity drill-down** (slice 6): shows the event trail (time, service,
   medicine or procedure, staff name) with the patient as a day code
   `P-XXXXXX`: HMAC-SHA256 of (facility, day, patient) under a key derived from
   the server's PII key with its own label. Stable for one patient all day at
   one facility (an officer can follow a journey), different the next day and
   elsewhere (not a standing identifier), not reversible without the server.
   Loaded on request, one facility and one day (last 90 days), at most 500
   events, and every load is written to that facility's audit log with the
   officer's Keycloak subject. The owner accepted this masked view on 10 Oct.
3. **Opening a named patient record** from the control room (slice 7) is a
   break-glass action: reason required, time-limited, written to the audit log,
   visible to the facility admin. **Not built until the health department's
   data-protection officer approves the purpose list.**

Every control-room read is audited with the monitor's subject and scope.

## Data model

- `monitor_scopes` (0097): `keycloak_sub`, `state_code`, `district` (NULL =
  whole state), `granted_by`, timestamps; unique (sub, state, district). Monitors
  have no `users` row, like superadmin: they belong to no hospital.
- `facility_pulse` (0097): one row per facility per 15-minute capture —
  `captured_at`, OPD today, OPD waiting, ED patients now, admitted now,
  beds total/occupied, lab orders pending, stock items below reorder level,
  items expiring within 30 days, staff on roster today. Indexed (facility,
  captured_at). Retention: 90 days of 15-minute rows, then daily.
- Later slices add `facility_bed_pulse` (by ward type), `equipment` +
  `equipment_status_events`, and a weekly `diagnosis_counts` rollup.

Status colour is computed when read, from documented thresholds
(beds ≥ 90% red, ≥ 75% amber; any stock-out amber, ≥ 5 red; no capture in
45 minutes = grey "not reporting").

## Slices (each its own PR)

Status 10 Oct: 1 #676, 2 #677, 3 #678, 4 #679, 5 #680, 6 #681 (stacked in that order); 7 not started.

| # | Slice | Contents |
|---|---|---|
| 1 | Foundation + status board | Role, scopes, pulse table, 15-min capture job, `/monitor/facilities` API, `/monitor` page with district filter |
| 2 | Beds and stock | Free beds by ward type; stock below reorder level and near expiry, per facility, with drill-down to item names |
| 3 | Disease trends | Diagnoses (ICD) this week vs last, by district, small-cell suppression, spike flag |
| 4 | Staff availability and cover | Rostered vs signed-in doctors; facility admin marks absent and reassigns the queue to a covering doctor |
| 5 | Equipment | Equipment register per facility, working/down/maintenance status, down-time alerts |
| 6 | Activity drill-down | Pseudonymous event trail per facility: first/last patient of the day, medicines dispensed, procedures, staff involved |
| 7 | Break-glass patient view | Only after DPO approval of purposes |

## Out of scope for now

CCTV feeds, ambulance tracking, ASHA field app, citizen bed-availability page
(listed in the comparison; separate projects).
