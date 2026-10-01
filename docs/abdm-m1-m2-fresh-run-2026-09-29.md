# ABDM M1 and M2 — fresh run sheet

Prepared 29 September 2026. This is a setup record and run order, not a pass
report. No milestone is complete until the observed outcome in each step below
has been seen end to end.

## 1. What was reset on 29 September

- **All 208 patients and their records were deleted**, including Ritik Kumar's
  chart (the ABHA ending 6441 linked on 28 September). That covers 72 tables of
  clinical, billing and ABDM data, 32 undelivered outbox events and all 27 ABDM
  delivery jobs. Every foreign key (389) was checked afterwards: no orphans.
- **Kept:** staff accounts (35), facility `IN0910034387`, departments, tariffs,
  catalogues, the append-only audit log (4,927 rows, hash chain untouched) and
  all callback receipts (evidence for NHA).
- **Backup taken first:**
  `backups/pre-purge-20260929/healthdoc_before_patient_purge_20260929T070742Z.dump`
  (verified restorable, contains all 208 patients).

## 2. Where to watch everything NHA sends

| Where | What it shows | How to open |
|---|---|---|
| Webhook inbox | Every request NHA sends to `/api/v3/*`, with receipt ID, request IDs, HealthDoc's reply status, and a redacted body structure | http://127.0.0.1:8766 |
| Postman | The same receipts, through **HealthDoc — Local Webhook Inspector**: 01 latest 50, 02 correlate a REQUEST-ID, 03 inspect one receipt, 04 queue counts | Postman |
| Browser | What each screen asked HealthDoc and what it answered | DevTools → Network, Preserve log, filter `abdm` |

- Inbox and Postman both read the same local console. If either shows nothing,
  check the console is running before concluding NHA sent nothing:
  `cd .local-archive/worktrees/next-phase-20260926 && python3 scripts/abdm_webhook_console.py`
- An unexpected path under `/api/v3/` is recorded as `/api/v3/<unmatched>`; its
  exact path is in the nginx access log. Paths outside `/api/v3/` are refused at
  Cloudflare and never reach HealthDoc.
- **NHA's replies to our requests** (not callbacks) appear in admin
  **ABDM delivery jobs**. From 29 September a refusal without a documented code
  records its body's field names, for example
  `AbdmAuthError:request:401:shape=json{message,status}`.

## 3. Before starting

1. `docker ps` shows backend, frontend, nginx, keycloak, postgres, redis, mongo
   and minio up.
2. Public callback GET returns **405**:
   `curl -s -o /dev/null -w '%{http_code}' https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token`
3. Inbox http://127.0.0.1:8766 loads; Postman **04 Queue and received-content
   counts** returns 200.
4. **Decide the M2 author question (section 6) before creating the M2 record.**

## 4. M1 — run order

Participant enters every OTP in the browser. Record case, UTC time and request
IDs only — never OTPs, tokens, Aadhaar or ABHA numbers.

1. **Register** the participant as a new patient (reception → registration).
2. **Verify existing ABHA by ABHA number** → OTP → *ABHA verified and linked* →
   **Download NHA ABHA card**.
3. **Verify by ABHA address** (fixed 29 September: now uses NHA's
   `/v3/phr/web/login/abha/*` with scope `abha-address-login`). Use a second
   chart or unlink first. Expect the address to be linked; the number appears
   only if NHA discloses it in full. The card comes from the PHR card endpoint.
4. **Verify by Aadhaar OTP** and **by mobile** if assigned in the workbook.
5. **Scan-and-Share** (fixed 29 September: a shared address no longer fails the
   share). Participant scans the facility's sandbox QR for `IN0910034387` in the
   PHR app and shares. Watch for POST `/api/v3/hip/patient/share` in the inbox;
   then Queue → **ABDM Scan & Share** shows the ticket; check it in.
6. **Create ABHA** only for a consenting participant who has none.

## 5. M2 — run order

1. As doctor, create and **finalize** one record for the patient (OPD visit →
   consultation → end encounter). Each finalized document is one care context.
2. Start the scoped delivery runner and keep its output:
   `docker exec -it healthdoc-backend-1 python -m scripts.run_abdm_test_session --facility-id 00000000-0000-0000-0000-000000000101 --expected-service-id IN0910034387 --execute 2>&1 | tee -a /Users/ritikkumar/Desktop/healthdoc/backups/abdm-runner-$(date -u +%Y%m%dT%H%M%SZ).log`
3. Doctor → `/doctor/abdm` → select the record → **Link selected documents**
   once. NHA allows three token generations per ABHA address per 24 hours; do
   not repeat on failure.
4. Expect, in order: POST `/api/v3/hip/token/on-generate-token` (token), then
   our link request, then POST `/api/v3/link/on_carecontext`, then **confirmed**.
5. In the PHR app: find the HealthDoc record, request/approve consent. Expect
   POST `/api/v3/consent/request/hip/notify`, then
   POST `/api/v3/hip/health-information/request`, then an outgoing transfer job,
   then the record rendered in the PHR app.

## 6. Open items that need a decision or NHA

### The 28 September link failure — ask NHA

After the service-ID cutover NHA's token callback worked for the first time,
but the next call was refused:

| Step | REQUEST-ID | UTC, 28 Sep | Result |
|---|---|---|---|
| Generate link token, HIP `IN0910034387` | `50f18e41-4f5a-5c98-98b4-227982de98a9` | 12:43:45 | 202 |
| NHA callback `on-generate-token` | `b825f8dd-d7cf-4785-8383-b373f4fb5bd1` | 12:43:49 | carried `abhaAddress` + `linkToken`; accepted 202 |
| `POST /api/hiecm/hip/v3/link/carecontext` with that token | `4143507d-6870-51f1-ba77-07dcdc80d01d` | 12:43:49, 12:44:10 | **401**, no ABDM error code |

HealthDoc's request matches NHA's own collection (same path; `REQUEST-ID`,
`TIMESTAMP`, `X-CM-ID: sbx`, `X-HIP-ID`, `X-LINK-TOKEN`, bearer session) and the
token was used 4 seconds after issue. A session refresh and retry also got 401.
Question for NHA: *why was link/carecontext request `4143507d…` refused with 401
when the link token from callback `b825f8dd…` was used immediately for the same
ABHA address and HIP?* If the next run fails the same way, the job will now also
record the refusal body's field names — add that to the ticket.

### M2 record transfer needs an authorised author

Transfer refuses a document whose author has no registration number.
`dev.doctor` has none, and the one approved synthetic WellnessRecord
(`fa563849…`) was deleted in the reset. Linking does not need this; transfer
does. Choose one before step 5.1:

- enter the treating clinician's **genuine** sandbox HPR registration number on
  their HealthDoc profile (Admin → Users → Profile), or
- create one new record titled `ABDM SANDBOX TEST — SYNTHETIC WellnessRecord; …`
  and explicitly approve its care-context ID in
  `ABDM_SANDBOX_LOCAL_AUTHOR_CONTEXT_IDS`. This is a per-document opt-in; never
  widen it to other records or invent a registration number.

## 7. Restart rules

- **Keycloak keeps its data inside its container** (dev mode, no database).
  `docker compose down`, `--force-recreate` or removing that container deletes
  every staff login. Use only `docker stop` / `docker start`.
- After a Docker or Mac restart:
  `docker start healthdoc-postgres-1 healthdoc-mongo-1 healthdoc-redis-1 healthdoc-minio-1 healthdoc-keycloak-1 healthdoc-backend-1 healthdoc-frontend-1 healthdoc-nginx-1`
- The stack is mounted from three worktrees under `.local-archive/worktrees/`
  (backend: `next-phase-20260926`; frontend: `abdm-service-cutover-20260926`;
  nginx and Keycloak: `abdm-runtime-recovery-20260925`). Do not delete them.
- The compose override the containers were created with lived in `/private/tmp`
  and is gone. A faithful copy is at
  `.local-archive/runtime/healthdoc-runtime-override.yml` (it points `.env` and
  the TLS certificates at the main checkout). Keep runtime files out of
  `/private/tmp`.
