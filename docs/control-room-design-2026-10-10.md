# Control room (state / district monitoring) — design

Date: 10 October 2026. Status: slices 1–6 built (PRs #676–#681); runs on its own server (see Deployment); slice 7 waits for DPO approval.
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

Board, drill-down and trend reads are written to the application log with the
officer's subject; activity-trail reads (patient-level, masked) are written to the
facility's audit table.

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

## Deployment: its own server, address and login (owner, 10 Oct)

BHAVYA runs its Command and Control Center apart from the HIMS: the HIMS is
`hims.bhavyabiharhealth.in`, the command centre `dashboard-1.bhavyabiharhealth.in`
with its own OTP login, and the ASHA dashboard a third host. The owner chose the
same shape: the control room on its own machine and address, with its own login.

| Piece | Hospital server (`PUBLIC_HOST`) | Control-room server (`CONTROL_ROOM_HOST`) |
|---|---|---|
| Compose file | `infra/docker-compose.prod.yml` | `infra/docker-compose.control-room.yml` |
| API | `API_MODE=hospital`: every hospital route, **no** `/monitor` | `API_MODE=control_room`: health, session login/logout and the four `/monitor` reads, nothing else (pinned by `tests/test_api_mode.py`) |
| Login | Keycloak realm `healthdoc` (staff) | Realm `healthdoc-control`: only the `monitor` role, client `healthdoc-control-frontend`, TOTP forced, served at this address (`frontendUrl`) |
| nginx | `/monitor` and the control realm answer 404 | Only `/monitor`, `/login`, assets, `/api/` and the control realm; the staff realm, the Keycloak admin console and every hospital page answer 404 |
| Database | Owner role | `healthdoc_control_room` (`infra/control-room/db-role.sql`) |
| 15-minute capture | Runs here, with full access | Not run here |

Why the capture stays on the hospital server: counting needs the clinical
tables, patients included (ABHA-linked visits for the adoption figures). The
control-room role therefore never needs `patients` and has no access to it. It
reads the snapshots, the officers' areas, ICD titles, and for the audited
activity trail the event tables, plus staff names (not their email or mobile).
It can insert its trail-audit rows but not read the audit log, and has no
UPDATE or DELETE anywhere. `tests/monitor/test_control_room_db_role.py` reruns
every control-room test with the officer endpoints executing as that role, and
checks that patients, ABHA numbers, staff contacts, consent, the audit history
and clinical writes are all refused.

One Keycloak, two realms: both realms live in the central Keycloak. The control
server's nginx proxies only `/auth/realms/healthdoc-control/` (and theme
assets, GET only) to it over the private network. `KC_HOSTNAME` stays pinned to
the hospital address; the control realm's `frontendUrl` overrides it for that
realm alone. This was checked on Keycloak 25 configured like production: the
control realm's issuer is `https://<CONTROL_ROOM_HOST>/auth/realms/healthdoc-control`
whichever host a request arrives on, and the staff realm keeps the hospital's.
The control API trusts only that issuer and audience.

Officers are created by the hospital server's superadmin
(`KEYCLOAK_MONITOR_REALM=healthdoc-control`), in the control realm, so an
officer account cannot sign in to the hospital address at all.

### Setting it up

1. Make the private-link certificates (any machine with openssl):
   `infra/control-room/make-private-certs.sh <dir> <hospital private IP>`.
   Hospital server gets `private-server.crt` and `.key`; the control-room server
   gets `private-ca.crt` only; keep `private-ca.key` offline.
   Hospital server, `.env.production`: set `CONTROL_ROOM_HOST`,
   `PRIVATE_BIND_ADDRESS` (its private-network address) and
   `PRIVATE_TLS_CERT_PATH` / `PRIVATE_TLS_KEY_PATH`. PostgreSQL (5432) and
   Keycloak's HTTPS (8443) then listen on that address: **firewall both to the
   control-room server only.** Both links are encrypted and verified (see
   Encryption below), so this firewall is defence in depth, not the only lock.
2. Hospital server, once, as the database owner:
   `psql -f infra/control-room/db-role.sql`, then
   `ALTER ROLE healthdoc_control_room LOGIN PASSWORD '<random>'`.
3. Redeploy the hospital stack: realm-init renders both realms; the backend
   now runs in hospital mode; `monitor-capture` keeps running there.
4. Control-room server: copy `.env.control-room.example` to `.env.control-room`
   (same PII key as the hospital server, since the trail's day codes derive
   from it), add a TLS certificate for `CONTROL_ROOM_HOST`, build the
   control-room frontend image (its realm and client are build arguments) and
   `docker compose --env-file .env.control-room -f infra/docker-compose.control-room.yml up -d`.
5. Superadmin creates officers on the hospital address (Platform → Control-room
   officers); officers sign in at `https://<CONTROL_ROOM_HOST>/monitor` and
   enrol their OTP at first sign-in.

An existing deployment's Keycloak already holds the staff realm, and import
skips realms that exist, so the control realm is imported on the next restart
without touching staff accounts.

The production realm render now also drops the `dev.*` accounts the source
realm carries. Before this, Keycloak 25 refused to start on a fresh production
install: their shared dev password fails the production password policy.

### Encryption between the servers

Both links from the control-room server to the hospital server are TLS, with
the server's certificate checked against a private CA and its name checked:

| Link | Encrypted by | Verified by | Refused |
|---|---|---|---|
| Control-room API → PostgreSQL | `ssl=on` (TLS 1.2+) | `DATABASE_SSL_CA_FILE`: chain + host name (verify-full) | Control-room role without TLS (`infra/control-room/pg_hba.conf`) |
| Control-room API → Keycloak signing keys | Keycloak HTTPS on 8443 | `JWT_JWKS_CA_FILE`, for that fetch only | Plain `http://` keys URL (the server will not start) |
| Control-room nginx → Keycloak login | Keycloak HTTPS on 8443 | `proxy_ssl_verify` against the CA, name `PRIVATE_TLS_NAME` | Any certificate not from the CA or not for that name (502) |

The control-room API refuses to start in production if either link is not
configured for verified TLS. Containers on the hospital server keep talking to
PostgreSQL and Keycloak inside its own Docker network, as before.

Checked end to end on 10 October 2026 with the production Compose services
(PostgreSQL 16, Keycloak 25 in `start` mode) and the control-room nginx:
the app's own engine connected as the control-room role over TLS 1.3; the
same role without TLS was refused by `pg_hba.conf`; a certificate from another
CA and a name not in the certificate were both refused; the hospital's own
plaintext connection inside Docker still worked; the signing-key fetch worked
with the private CA and failed with another CA or the public trust store;
nginx returned the control realm with the right certificate and 502 for a wrong
name or another CA.

Rotating: run the script into a new directory, put the new server certificate
on the hospital server and the new CA on the control-room server, run
`docker compose up -d --force-recreate private-tls-init postgres keycloak`, then
recreate the control-room stack.
The script's certificates last 825 days (`DAYS=` to change).

Not done here: a second Keycloak instance for full separation of the identity store. BHAVYA's public
material does not say whether its command centre has its own identity store;
one Keycloak with a separate realm keeps one place to patch and back up.

## Out of scope for now

CCTV feeds, ambulance tracking, ASHA field app, citizen bed-availability page
(listed in the comparison; separate projects).
