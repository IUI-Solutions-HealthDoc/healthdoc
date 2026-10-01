# HealthDoc: run M1 and M2 now; prepare M3 separately

Updated 26 September 2026. This is the current operator guide, superseding
older instructions about sender IDs, pending historical jobs and a missing
browser webhook viewer. It is not an ABDM certification/pass report.

**Start here:** application/logins in sections **2A–2C**, Postman in **4**,
M1 in **6**, start the scoped runner in **7**, then M2 in **8**. Keep section
**5** open to inspect callbacks and use section **10** to report failures.

## 1. What you can do now

**The missing M3 requester registration number, identifier type and registry
URI do not block M1 ABHA verification or HIP-initiated M2 linking.** Start
those now. M2 record transfer additionally needs a valid, finalized clinical
document and valid authorship; successful linking is not successful transfer.

| Case | Run now? | Actual completion evidence |
|---|---|---|
| M1 existing ABHA verification and card | Yes, with the consenting participant and OTP | Correct chart linked to verified identity; NHA card available |
| M1 new ABHA enrolment | Only with an eligible consenting participant who needs enrolment | Enrolment, required mobile/address continuation and card complete |
| M1 Scan-and-Share | With the facility's correct sandbox QR and PHR app | Profile callback, reception ticket and patient-side acknowledgement |
| M2 HIP-initiated document linking | Yes, for eligible finalized documents and current consent | Token callback, link-confirmation callback and confirmed document in PHR |
| M2 encrypted record delivery | After linking, using a valid document and PHR consent/fetch | Consent/data-request callbacks, encrypted delivery and correct record rendered in PHR |
| M2 PHR-initiated discovery → OTP → linking | Not yet: no approved SMS provider/HTTPS relay | Real OTP delivery and confirmed linkage; do not bypass OTP |
| M3 HealthDoc requesting records as HIU | Wait for the authorized clinician's complete requester profile | Consent → artefact → encrypted receipt → decrypt/validate/store/render, plus refusal cases |

The runtime has one previously approved, specifically allowlisted synthetic
WellnessRecord author context. That is not blanket permission to share all
dev-doctor records or an NHA certification approval. Do not expand the
allowlist, invent registration details or relabel historical clinical authors.
If another document fails the author check, report it and use a legitimately
authored document; do not remove the check.

Complete the cases assigned in your NHA workbook. One successful OTP or link
does not complete an entire milestone. Export support currently covers
Prescription, DiagnosticReport, OPConsultation, DischargeSummary and
WellnessRecord; do not claim unimplemented HI types or every assigned case
passed. ImmunizationRecord, HealthDocumentRecord and Invoice need separate
support/acceptance if required by your assigned cases.

## 2. Setup already performed and verified

- Branch: `work/next-phase-20260926`, based on merged main `30a6176`.
- Working source: `/Users/ritikkumar/Desktop/healthdoc/.local-archive/worktrees/next-phase-20260926`.
- Backend now runs from this worktree; local health returned **200**.
- Facility, HIP sender and HIU sender: **IN0910034387 — HealthDoc Facility**.
- Bridge: **SBXID_053401**; callback base: **https://abdm.healthdoc.world**.
- Sandbox gateway: **https://dev.abdm.gov.in**, consent manager `sbx`.
- Database at migration **0088**; receipt capture enabled.
- **22 historical jobs remain frozen**, not rewritten or retried. The other
  facility's pending job remains untouched.
- Both Postman collections below are imported. The new inspector's **Latest
  50 webhook receipts** and **Queue and received-content counts** requests
  returned **200 in Postman**.
- All **16 public callback GET probes** returned **405 with receipt IDs** in
  a separate script check. The token-callback GET was also refreshed in
  Postman and returned 405. These are synthetic routing checks, not NHA POSTs.
- The read-only console is running at **http://127.0.0.1:8766**. Chrome
  automation returned `ERR_BLOCKED_BY_CLIENT` when opening it; its rendered
  browser page has not been visually accepted. Its HTTP/API and Postman
  access are verified. You can use Postman regardless.
- The new facility/cutoff-scoped delivery runner passed its live **dry run**.
  **It has not been started in execute mode. Start it just before M2 below.**
- No participant OTP, token-generation, consent request or clinical transfer
  was sent as part of this setup.

The snapshot still has zero stored link tokens, zero stored transfer keys
and zero received-content rows. These counts are not lifetime success counts
and can change or be cleared by retention. M3 requester fields were checked
separately: the current `dev.doctor` profile lacks all three registration
fields. The global status request without a selected link is not a reliable
profile-completeness check by itself.

## 2A. Required dashboards, usernames and passwords

These are **local development accounts only**, not NHA/PHR logins or real
clinician credentials. The seed script sets the password below. A live
Keycloak readback on 26 September confirmed all three accounts exist and are
enabled. A new browser sign-in was **not** completed in this check: Chrome
stopped at the local certificate warning. Do not assume a changed password
has been reset; no password reset was performed.

| Use | Local username | Seeded password | Open after signing in |
|---|---|---|---|
| M1 ABHA verification/card | `dev.receptionist` | `devpass` | https://localhost/receptionist/registration |
| Record/review actual local consent | `dev.receptionist` or `dev.doctor` | `devpass` | https://localhost/consent |
| M1 Scan-and-Share reception | `dev.receptionist` | `devpass` | https://localhost/receptionist/queue |
| M2 finalized-document linking/status | `dev.doctor` | `devpass` | https://localhost/doctor/abdm |
| Clinical consultation workspace, when an authorized record is needed | `dev.doctor` | `devpass` | https://localhost/doctor/consultation |
| Outgoing ABDM jobs/errors | `dev.admin` | `devpass` | https://localhost/admin/abdm-sync |
| Later M3 clinician-profile configuration | `dev.admin` | `devpass` | https://localhost/admin/users |
| Incoming webhook evidence | No HealthDoc login | None | http://127.0.0.1:8766 or Postman inspector |

The doctor lands at `/doctor/dashboard` by default; open `/doctor/abdm`
after login. Admin cannot substitute for the receptionist/doctor in those
role-restricted screens. **Do not use `dev.superadmin` for this workflow.**

Three different sign-ins are involved:

- **HealthDoc:** the local accounts above. Log in through https://localhost;
  Keycloak's HealthDoc form should remain under the same origin's `/auth/`.
  Do not use the Keycloak administrator console as the application login.
- **Sandbox PHR/ABHA app:** the participant's own sandbox ABHA login and
  OTP. `dev.patient` and `devpass` do **not** log in to that app. HealthDoc's
  local patient portal is not the external PHR needed for this test.
- **Postman → NHA:** the existing client secret and session token in Local
  Vault, not any of the passwords above. Never put `devpass` into the NHA
  session request or share the real client secret.

Use separate Chrome profiles for reception/doctor/admin if you want all open
at once. Separate tabs in the **same** profile share the Keycloak session:
opening another tab is not switching roles. Otherwise sign out, then sign
back in with the next role. If a login is rejected, report the username and
error only; do not repeatedly retry, disable guards or reseed the database.

## 2B. Start the whole existing local application safely

**It is already running; normally skip straight to the login table.** Fresh
checks returned local API health200, public callback GET405 and local viewer200.
Postgres, MongoDB, Redis and MinIO report healthy. Backend, frontend, nginx and
Keycloak are up. Migration is0088. No reinstall, re-enrolment or database reset
is needed to start this walkthrough.

### After a normal Mac/Docker restart

1. Open **Docker Desktop** and wait until its engine is running.
2. Open Terminal. Inspect only the HealthDoc containers:

   ```sh
   docker ps -a --filter name=healthdoc- --format 'table {{.Names}}\t{{.Status}}'
   ```

3. If the listed containers exist but are stopped, start them **without
   recreating them**. This preserves the configured local Keycloak instance,
   source mounts, application environment and data volumes:

   ```sh
   docker start healthdoc-postgres-1 healthdoc-mongo-1 healthdoc-redis-1 healthdoc-minio-1 healthdoc-keycloak-1
   docker start healthdoc-backend-1 healthdoc-frontend-1 healthdoc-nginx-1
   ```

4. Allow startup to settle, then check:

   ```sh
   curl --silent --show-error \
     --cacert /Users/ritikkumar/Desktop/healthdoc/infra/nginx/certs/dev.crt \
     https://localhost/api/v1/health
   docker exec healthdoc-backend-1 alembic current
   curl --silent --show-error --dump-header - --output /dev/null \
     https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token
   ```

   Require successful local health, revision0088 and public **405 with
   X-HealthDoc-Receipt-ID**. The last command is a GET probe, not a token request.
5. Open **https://localhost**. If Chrome shows the expected self-signed
   development certificate warning, you must personally verify it is this
   local HealthDoc endpoint and handle the trust prompt. Automation cannot
   accept it for you. Do not ignore certificate warnings on NHA or the public
   `abdm.healthdoc.world` domain.
6. Keep the existing named Cloudflare tunnel running. This Mac has the
   installed system service `com.cloudflare.cloudflared`; it is not a Docker
   container. A public callback405 confirms reachability at that moment. If
   local health works but the callback returns502, inspect that existing
   tunnel service/origin before any OTP/link request. Do not create a new
   random tunnel URL or re-register the bridge to fix a local startup problem.
7. Start the viewer as described in section3 if it is no longer running.
8. Start **only** the session delivery runner in section7, immediately before
   M2. It is separate from the API and viewer; opening a page does not start it.

### Stop if containers or source folders are missing

Do not substitute `make setup`, `docker compose down -v`, prune volumes or
recreate Keycloak during this live-test setup. The setup script deliberately
resets dev passwords/roles and seeds data; that is not a harmless restart.
Do not reset the database or replace `.env`/encryption keys. If a container is
missing, have an engineer recover it against the existing volumes/configuration
before continuing.

Retain all currently mounted source worktrees:

- Backend: `.local-archive/worktrees/next-phase-20260926/backend`.
- Frontend: `.local-archive/worktrees/abdm-service-cutover-20260926/frontend`.
- Nginx: `.local-archive/worktrees/abdm-runtime-recovery-20260925/infra/nginx`.
- Certificate directory: `/Users/ritikkumar/Desktop/healthdoc/infra/nginx/certs`.

The three worktrees are under `/Users/ritikkumar/Desktop/healthdoc` and were
read back from the running container mounts. Deleting a mounted branch folder
can break the runtime even if the Git branch was merged. Keep your original
private `.env` in place; never upload it to Postman or chat.

## 2C. The exact order for your first M1 → M2 walkthrough

1. **Postman:** perform section4 session + registration GETs. Do not save the
   session response body; it contains the access token.
2. **Receptionist:** log in as `dev.receptionist`, select the existing
   consenting sandbox participant's chart and perform section6 ABHA verification.
   The participant enters the OTP. Confirm verified identity/card.
3. **Receptionist, Consent screen:** select that same chart and record/review
   the actual Clinical Review consent, correct channel and intended future
   expiry. Do not select `digital_otp` unless that consent was actually obtained
   that way. Local consent does not replace the later PHR consent.
4. **Terminal:** start section7's new-session runner before queueing a link.
5. **Doctor:** sign in as `dev.doctor`, go to `/doctor/abdm`, search by the
   participant's **name and date of birth**, and select the correct result.
6. In **Share this facility's finalized documents**, select one authorized,
   eligible **not linked** record and click **Link selected documents** once.
   The separate **Request consent** / incomplete-requester panel is for M3;
   do not fill invented requester fields or use that button for this M2 run.
7. **Postman inspector:** observe the token and link-confirmation callbacks.
   **Doctor:** Refresh link status until the actual outcome is visible.
8. **Participant's PHR app:** inspect the linked HealthDoc record, follow its
   view/fetch flow, and approve the actual requested scope if they consent.
9. **Postman inspector + Admin:** follow HIP consent/data-request receipts
   and outgoing transfer jobs. Require the PHR to render the correct document.
10. Save only redacted evidence. Stop the session runner when finished.

If the document list is empty, all records are pending, or author validation
fails, **stop and report that exact state**. Do not create arbitrary clinical
history, relabel an old author, bulk-retry frozen work or create duplicate links.
The existing specifically approved synthetic WellnessRecord is usable only
for its intended consenting participant/context. Other documents require their
own valid authorship. There is no guarantee every existing dev record is exportable.

M1 creation/Scan-and-Share and additional M2 cases follow sections6/8 when
their prerequisites are present. This walkthrough targets the available
end-to-end HIP-initiated path, not a declaration that every NHA case passed.

## 3. Keep these windows open

1. Docker Desktop, with HealthDoc running; keep the Mac awake.
2. Postman:
   - **HealthDoc ABDM — Readiness and Webhook Evidence (24 Sep)**.
   - **HealthDoc — Local Webhook Inspector (26 Sep)**.
3. Browser: **https://localhost**. Use separate profiles or sign out when
   switching receptionist, doctor and admin roles.
4. Participant's **sandbox** PHR/ABHA app for OTP/consent and record viewing.
5. Optional browser inbox: **http://127.0.0.1:8766**.

If the local inbox is no longer running, open a Terminal and run:

```sh
cd /Users/ritikkumar/Desktop/healthdoc/.local-archive/worktrees/next-phase-20260926
python3 scripts/abdm_webhook_console.py
```

Keep that Terminal open. Ctrl-C stops only the viewer, not HealthDoc or its
public callback. If it says the port is already in use, open the existing
viewer rather than starting another. The console is intentionally loopback
only and read-only. **Do not tunnel it, bind it to a LAN address, or expose
it as the registered bridge.** No secrets need to be entered in it.

Imports, if needed after moving machines:

- [Readiness collection](postman/healthdoc-abdm-readiness.postman_collection.json)
- [Webhook inspector collection](postman/healthdoc-webhook-inspector.postman_collection.json)

Import those JSON files only—not `.env`, populated environments or the project
folder. Keep Local Vault secrets private and never save token responses as
examples. Do not use Collection Runner on the whole readiness pack.

## 4. First perform these non-clinical checks in Postman

### A. Public routing and local health

1. In readiness folder **00 Public callback routing**, send **M2 token
   callback — GET probe, expect 405**.
2. Expect **405** and response header **X-HealthDoc-Receipt-ID**. Record the
   receipt UUID. Do not change this probe to POST to make it look successful.
3. In folder **03 Local API**, send the health GET. Expect **200**. If Postman
   does not trust the approved local certificate, configure that certificate
   as a trusted CA in Postman; keep TLS verification enabled. Browser trust
   and Postman trust are separate.
4. Public `/` and `/api/v1/health` are intentionally not exposed. Use the local
   health URL; an actual public callback **502** is an origin/tunnel failure.

### B. Session and current registration

1. Open the readiness collection's **Variables**. Set `arm_session_once`
   to `yes` immediately before sending the session request; it resets to `no`.
2. Send **01 Session — manual arm and Local Vault required** in folder **02
   NHA registration**. The configured client secret stays in Local Vault as
   `healthdoc-abdm-client-secret`, restricted to `dev.abdm.gov.in`.
3. Require **200** and passing tests. The script puts the short-lived token
   in Local Vault as `healthdoc-abdm-access-token`. **Do not copy its body**.
4. Send **02 Read bridge and services**, then **03 Read IN0910034387**.
5. Require **200**, bridge `SBXID_053401`, URL `https://abdm.healthdoc.world`,
   service `IN0910034387`, and `isHip`, `isHiu`, `active` all true.
6. Do not register the service again or change its callback URL. If values
   differ, stop and share only the redacted registration result.

Exact gateway paths already configured in this collection:

| Method | Sandbox path |
|---|---|
| POST | `/api/hiecm/gateway/v3/sessions` |
| GET | `/api/hiecm/gateway/v3/bridge-services` |
| GET | `/api/hiecm/gateway/v3/bridge-service/serviceId/IN0910034387` |

The scripts generate current UTC timestamps and request IDs. Do not paste a
stale timestamp, retry in a loop, or replace Vault with a cloud-synced token.
An unarmed/skipped request is not a passed request.

## 5. How to see what arrived from NHA or a source HIP

### In Postman

1. Open **HealthDoc — Local Webhook Inspector (26 Sep)**.
2. Send **01 Latest 50 webhook receipts**. Its response lists incoming
   method/path, receipt ID, timestamps, request IDs and HealthDoc's status.
3. Select a receipt and copy its `id` (a UUID, not a patient/link identifier).
4. In this collection's Variables, set `receipt_id` to that UUID. Send **03
   Inspect one redacted callback and reply**. The response includes the
   minimized body/header structure and recorded response evidence.
5. To trace one outbound operation, set `original_request_id` to its original
   gateway REQUEST-ID. Send **02 Correlate original REQUEST-ID**. It matches
   incoming `request_id` or nested `response_request_id`.
6. Send **04 Queue and received-content counts** for current diagnostic
   counts. These counts cover the local database, not just this participant.

These requests already supply `X-HealthDoc-Operator-View: 1`. They require
no bearer token and make **no NHA call**. A 503 means the reader failed, not
that there are no callbacks. A 400 means check the UUID/query. An empty list
can also mean no match or expired evidence; the inspection window is seven
days. Do not guess receipt IDs.

### In the optional browser inbox

Open **http://127.0.0.1:8766**. Auto-refresh runs every five seconds. **POST
only** is selected initially: uncheck it to see the synthetic GET probes.
Filter by the original REQUEST-ID, click **Inspect**, then **Copy redacted
evidence**. Review it before sharing. It omits IP claims as well as the
credentials/patient data removed by the existing backend receipt reader.

### Do not confuse these three responses

| Where you look | What it means |
|---|---|
| Direct NHA request in Postman → Response | NHA's immediate reply to that request |
| Incoming webhook receipt → `status_code` | HealthDoc's HTTP reply to the incoming caller, **not** NHA's earlier upstream status |
| Browser Network → `/api/v1/abdm/...` | HealthDoc's API response to the browser; may say queued before a worker contacts NHA |

A 202, a successful job, or an incoming callback alone is not final business
success. Inspect the callback payload/outcome and the resulting document/link.
`nha_origin_verified: false` deliberately means receipt capture is not an
authentication claim; IP/header claims cannot prove who sent a request.

For browser diagnostics open DevTools → **Network**, enable Preserve log,
filter `abdm`, select the action's request and view **Response**. Keep tokens,
OTP/Aadhaar, ABHA, names, contact details and clinical text out of screenshots.
Do not export/share an unredacted HAR or Postman console dump. Do not describe
a browser response as the raw upstream NHA response if it is only a local
queued acknowledgement. Mark the upstream status “not captured” when unknown.

## 6. M1 — perform now in HealthDoc

### Existing ABHA (start with this)

1. Sign in as receptionist; open **https://localhost/receptionist/registration**.
2. Search for the participant's existing chart. Select **Use this patient**;
   do not create a duplicate merely to repeat verification.
3. Under **ABHA identity**, choose **Use existing ABHA** and the correct
   supported verification method. Enter the matching sandbox identifier.
4. With the participant's consent, click **Send OTP** once. Participant
   enters the OTP directly; then **Verify and link**.
5. If multiple accounts are offered, select the correct account and click
   **Link selected account**.
6. Require **ABHA verified and linked** for this chart. Download the **NHA
   ABHA card** if offered; the hospital's UHID card is a different document.
7. Record the case outcome and safe request IDs. M1 identity/OTP/card calls
   are normally synchronous: **do not wait for an M2 linking-token webhook**.

For wrong/expired OTP use the app's correction/resend controls, not repeated
fresh verification requests. A failure can be investigated without repeating
the participant's private identifier in chat.

### Other assigned M1 cases

- **Create ABHA:** only for an eligible consenting participant who needs it.
  Have them review enrolment consent, complete Aadhaar OTP, communication-mobile
  OTP if required, select/save an ABHA address, then obtain the card. Do not
  create a second identity for someone who already has one.
- **Scan-and-Share:** use the facility's sandbox **Manage QR**/approved QR,
  not a home-made IN-number QR or the local reception-ticket barcode. The
  participant scans and shares in the sandbox PHR app. Watch POST
  `/api/v3/hip/patient/share`; then receptionist **Queue → ABDM Scan & Share**.
  Check reception ticket plus participant-side acknowledgement/token. Exact
  redelivery must not create a duplicate ticket/patient.

Do not mark untested mandatory cases complete. Broader M1 method coverage must
be checked against the assigned workbook; current ABHA-address verification
uses mobile OTP, not general auth-method discovery/address-Aadhaar selection.

## 7. Start controlled delivery immediately before M2

This is the only new command here that intentionally enables delivery to the
sandbox. It processes **new jobs for this facility** after the printed start
time, including follow-up acknowledgements/transfers. Only perform approved
participant actions while it runs; do not run unrelated tests concurrently.

In a separate Terminal:

```sh
docker exec -it healthdoc-backend-1 python -m scripts.run_abdm_test_session \
  --facility-id 00000000-0000-0000-0000-000000000101 \
  --expected-service-id IN0910034387 \
  --execute
```

Start this **before** clicking Link selected documents. Record its printed
`created_since` UTC timestamp; keep the Terminal open. No output while idle
is normal. “attempt completed” is not a success assertion—check the job and
callback. Ctrl-C stops this runner; it does not stop callback receipt capture.

If restarting the same session, use the **same recorded cutoff**, otherwise
already-queued session jobs would be excluded:

```sh
docker exec -it healthdoc-backend-1 python -m scripts.run_abdm_test_session \
  --facility-id 00000000-0000-0000-0000-000000000101 \
  --expected-service-id IN0910034387 \
  --created-since REPLACE_WITH_THE_SESSION_CREATED_SINCE \
  --execute
```

To inspect without dispatch, omit `--execute`. The script checks sandbox
gateway/CM, all three sender IDs and the facility mapping, then applies the
facility/cutoff inside the atomic claim. Existing leases/backoff/retry limits
remain. Frozen historical jobs and other facilities are excluded. It is not
a cleanup/retention worker. **Do not start the global `--mode all` worker or
unfreeze/retry historical jobs to make this test proceed.**

## 8. M2 — linking, then real record delivery

1. Check current local **https://localhost/consent** for the selected patient.
   Record only their actual decision, purpose/channel and intended expiry.
   Local consent is **not** approval of an ABDM PHR consent request.
2. Sign in with the appropriate doctor role, open **https://localhost/doctor/abdm**,
   search/select the correct chart, and inspect **Share this facility's
   finalized documents**. Each care context is one finalized document.
3. Choose one approved, eligible document with valid authorship. For an
   approved synthetic test, keep its synthetic label; do not invent diagnoses
   or sign historical test records as a real doctor.
4. With the scoped runner already active, click **Link selected documents**
   **once**. Keep the link/operation and original token REQUEST-ID from the
   API response/status. If the original ID is not exposed in the browser,
   an operator can read it using the link UUID:

   ```sh
   docker exec healthdoc-backend-1 python -m scripts.abdm_operational_status \
     --link-id REPLACE_WITH_NEW_LINK_UUID
   ```

5. In admin **https://localhost/admin/abdm-sync**, inspect **ABDM delivery
   jobs**. The new `link_token` job should be attempted. Do not use **Retry
   delivery** merely because the callback has not arrived.
6. In Postman inspector, require the correlated POST
   **/api/v3/hip/token/on-generate-token** and usable token metadata. Never
   display/share the actual token. HealthDoc queues the next linking step;
   the scoped runner handles eligible new work promptly.
7. Require POST **/api/v3/link/on_carecontext**. Click **Refresh link status**
   and require **confirmed**. Check the correct facility/record in the
   participant's sandbox PHR app.
8. In the PHR app, use its record fetch/view flow and have the participant
   review/approve the actual consent requested. App labels can differ by
   version. HealthDoc is HIP here; this is not the deferred HealthDoc-HIU
   requester form.
9. Watch **/api/v3/consent/request/hip/notify**, then
   **/api/v3/hip/health-information/request**. Require accepted consent scope,
   acknowledgement and a new `hip_transfer` job for that transaction.
10. Let the runner dispatch authorized transfer/notification jobs. Require
    the PHR/consumer to decrypt and render the correct document. **Confirmed
    link, push HTTP success, or context notification alone is insufficient.**
11. Capture redacted evidence for linking, transfer and PHR display. Exercise
    additional record types and refusal/revocation/expiry cases only as
    assigned and authorized. Stop the runner after the session.

The application's configured outgoing M2 paths (under dev.abdm.gov.in) include:

| Action | Path |
|---|---|
| Generate HIP link token | `/api/hiecm/v3/token/generate-token` |
| Link selected care contexts | `/api/hiecm/hip/v3/link/carecontext` |
| Notify context | `/api/hiecm/hip/v3/link/context/notify` |
| Acknowledge HIP consent | `/api/hiecm/consent/v3/request/hip/on-notify` |
| Acknowledge HIP data request | `/api/hiecm/data-flow/v3/health-information/hip/on-request` |

**Do not replay raw gateway examples independently in Postman for these
steps.** HealthDoc must first persist the operation/correlation and, for data
exchange, the required cryptographic state. The browser performs the clinical
operation; Postman displays registration results and the incoming evidence.
Do not add guessed database rows to accommodate an unrelated callback.

If token generation finishes but no callback arrives, capture correlation and
edge/receipt evidence before retrying. One accepted request does not justify
repeated requests or quota use. The old ambiguous transaction is not this
new-facility session.

## 9. What remains for M3 (do not substitute guessed values)

Obtain the authorized clinician's exact name plus genuine/NHA-approved
**registration number, identifier type and issuing registry URI**. A facility
manager HPID, a masked number or a hospital name cannot fill these by inference.
As facility admin, use **Admin → Users → Profile**, save the four fields on
the actual clinician account, and confirm correct facility/doctor role.
Completeness is not independent verification of professional authority.

Then follow section 9 of the [full M1–M3 runbook](abdm-self-service-webhooks-m1-m2-m3-2026-09-24.md#9-m3--request-receive-and-review-records-as-hiu):
request consent → patient decision → fetch granted artefact → request only
granted records → receive/decrypt/validate/store → view as original requester.
Use the inspector for the six HIU paths in that runbook. Test denial,
revocation, expiry and cross-patient/role refusal; also arrange retention/key
cleanup and external interoperability required by the assigned workbook.
Requester details unblock initiation, **not automatic M3 completion**.

## 10. Send back this evidence at the first failure

```text
Case: M1 verification / M1 Scan-and-Share / M2 token / M2 link / M2 transfer
UTC time:
Action clicked or exact Postman request name:
URL path (no patient identifiers in query):
Immediate NHA HTTP status (only if directly observed; otherwise not captured):
HealthDoc/browser HTTP status:
Original REQUEST-ID:
Incoming receipt UUID and callback path:
Redacted callback body/error and HealthDoc reply status:
Job kind/status/attempt count:
Observed chart/link/PHR result (no patient identifiers):
Expected result:
```

Use **Inspect one redacted callback and reply** or **Copy redacted evidence**.
Never paste client secret, bearer/link/profile token, OTP, Aadhaar/ABHA,
patient name/mobile, private key or clinical bundle. Review screenshots before
sending. For the session API share status/tests only, never its token body.

| Symptom | Next check |
|---|---|
| Inspector 503 | Docker/backend/reader availability; not “zero callbacks” |
| Callback GET 405 | Expected route probe; check actual POST next |
| Callback 502 | Restore origin/tunnel; do not regenerate tokens |
| POST 400/422 | Receipt's redacted validation shape, IDs and timestamp |
| POST 401/403 | Actual callback authentication/scope; never disable checks |
| `link_not_found` | Correlation to a persisted operation, not a fabricated row |
| Job remains pending | Runner on? Job created after correct cutoff? Backoff? Correct facility? |
| Job done but link unconfirmed | Token/link callback and payload outcome |
| Transfer fails author validation | Legitimate document author or specifically approved synthetic context |
| No receipt | ID/window/routing/edge/storage; absence alone does not prove NHA sent nothing |

## Verification of this setup, not of milestones

- Backend focused scope/durable-job/callback-evidence tests: **27 passed,
  1 skipped** (PostgreSQL-only case not exercised by this isolated run).
- Local console security/reader tests: **8 passed**.
- Offline Postman checks: readiness **21 requests / 42 scripts**; inspector
  **4 requests**. No network calls in these validation scripts.
- Backend Ruff check, JavaScript syntax and diff checks passed.
- Live checks: local health200, 16 public routing probes405+receipt,
  Postman inspector receipt list200 and status200, delivery dry-run only.
- Browser rendering of the new inbox remains unverified due the automation
  block described above. No live M1/M2/M3 acceptance asserted.

Reference contracts: supplied NHA Postman collections and current HealthDoc
routes/config. Official comparison references:
[NHA v3 callback constants](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/common/constants/GatewayURL.java),
[Postman Local Vault script access](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-vault/).
Use interactive desktop Postman for the reviewed Vault requests, not an
assumed CLI/Newman equivalent.
