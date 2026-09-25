# HealthDoc — self-service ABDM M1, M2 and M3 runbook

Updated: 25 September 2026. The queue and database counts below are explicitly
the 24 September snapshot; no live milestone transaction is inferred from them.
Audience: the HealthDoc owner, a facility administrator and the authorized test clinician.
This is an execution guide, **not a certificate or a claim that all milestones pass**.

**Later correction — 24 September, after the corrected screenshot:** use
**IN0910034387 — HealthDoc Facility**, not the earlier IN0911638718.
The screenshot shows hspsbx.abdm.gov.in software linkage, and NHA sandbox
GET readback independently confirms this service is active for **both HIP
and HIU**, under SBXID_053401 at https://abdm.healthdoc.world.
**Do not register it again or repeat the conditional service PUT below.**
The new HPID is masked, ending 6184; its professional/council application
is Draft, so clinician authority/full identifier are still unverified.
HealthDoc's local HFR setting and facility row now use the confirmed ID.
Its HIP/HIU sender settings still use the old service IDs; those pending jobs
have not been rewritten. See [Postman setup](postman/README.md).

## 1. Start here: what is actually ready

| Item | Observed state |
|---|---|
| HealthDoc browser | https://localhost — local frontend and issuer returned **200** after the 25 September container recovery; accept only the intended local certificate |
| Public callback base | **https://abdm.healthdoc.world** |
| Bridge/client ID | `SBXID_053401` |
| Registered services | **IN0910034387** active for HIP and HIU; older HIP/HIU service entries also remain |
| Correct facility supplied by you | **IN0910034387 — HealthDoc Facility**; supersedes the earlier incorrect ID |
| Corrected HPID screenshot | Masked, ending **6184**; Healthcare Professional & Facility Manager; application/council status **Draft**, not verified clinician authority |
| Registry environment | Corrected screenshot shows **hspsbx.abdm.gov.in**; association independently confirmed by NHA sandbox GET |
| New backend repairs | [PR #597](https://github.com/IUI-Solutions-HealthDoc/healthdoc/pull/597) merged into `staging`; the restored local backend runs its enum/ORM repair |
| Database | Backed up and upgraded from **0085** through **0087** on 25 September; `alembic current` reports `0087 (head)` |
| Public routing test | The public token callback initially returned **502** on 25 September because its origin containers mounted deleted temporary worktrees; after recovery it returned **405** to a safe GET, as expected for a POST-only route. No NHA transaction was sent. |
| Durable evidence | Receipt table and persistent nginx access logs exist; receipts survived backend recreation |
| 25 September queue snapshot | **21 context_notify + 1 link_context pending** for the affected local facility, plus one unrelated context_notify; 2 link_token jobs done. Do not switch HIP/HIU sender IDs blindly. |
| 24 September data snapshot | **0 stored linking tokens, 0 received-content rows, 0 stored transfer keys**; re-query before a milestone claim |
| Background processes | No standalone ABDM delivery or cleanup worker appeared in the 24 September inventory; re-check after restart |
| Test evidence | 809 focused isolated ABDM/Scan-and-Share/schema tests passed previously; not a complete live acceptance run |

An HTTP 202, a job marked done, a registered service, or an HPID alone does **not** complete M2/M3.
A successful milestone case needs its actual callback, business state and patient/clinician-visible result.
Full completion additionally needs the assigned NHA workbook and NHA review.

## 2. Where you can check webhooks

### A. Incoming NHA/HIP requests — use Terminal

There is currently **no browser webhook-inbox page**. Incoming evidence is deliberately operator-only, not exposed to every facility admin.

After the backend is running, open Terminal and run:

```sh
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --limit 20
```

This is read-only. It shows:
- `id`: HealthDoc's receipt ID;
- `request_id`: incoming REQUEST-ID;
- `response_request_id`: original operation ID from a nested response, when available;
- `path`, `method`, `status_code`, received/completed timestamps and expiry.

To correlate an operation, replace the placeholder with its UUID:

```sh
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --request-id ORIGINAL_REQUEST_UUID
```

To inspect one failed request's **redacted** body/header structure:

```sh
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --id RECEIPT_UUID --details
```

Use an actual receipt UUID, not a link UUID or ABHA number. Never paste tokens, OTPs, raw patient payloads or unredacted screenshots into a ticket.

**How to read the result:**
- `POST` plus matching original request ID and expected persisted state is useful transaction evidence.
- `GET 405` is normally your browser/probe reaching a POST-only route.
- `400`/422: inspect redacted validation locations, required headers and DTO shape.
- `404 link_not_found`: a handler was reached but the operation was not found; this differs from an nginx route 404.
- `202`: accepted for processing, not necessarily finished.
- Missing/null completion can indicate a process interruption; reconcile the operation before retrying.
- `nha_origin_verified: false` is intentional: receipt storage alone cannot authenticate who sent a request. IP/header claims alone are not proof of NHA origin.
- No rows may mean the wrong correlation ID, an expired seven-day window, no arrival, an edge rejection, or a receipt-storage problem. It does not alone prove NHA sent nothing.

### B. Persistent edge access logs — check traffic before the application

List the available daily files:

```sh
docker exec -u 0 healthdoc-nginx-1 ls /var/log/healthdoc
```

Read the selected day's callback traffic locally (change the date when needed):

```sh
docker exec -u 0 healthdoc-nginx-1 sh -c 'grep "/api/v3/" /var/log/healthdoc/access-2026-09-24.log | tail -50'
```

For live observation, Ctrl-C stops only the view:

```sh
docker exec -u 0 healthdoc-nginx-1 sh -c 'tail -f /var/log/healthdoc/access-2026-09-24.log'
```

Files are in the persistent `healthdoc_nginx-logs` Docker volume. Normal container recreation preserves it; **do not use `docker compose down -v`**.
Logs include receipt IDs and bounded forwarded-IP **claims**, not request bodies or authorization headers.
Review privately: IPs and other operational metadata should not be published raw.

Receipts have a seven-day inspection window. Expired receipts are hidden even before cleanup physically deletes them. Access files also have a seven-day operational retention policy. Archive sanitized certification evidence promptly under an approved retention policy; these stores are not permanent certification archives.

### C. Outgoing jobs — use HealthDoc in the browser

1. Sign in as the facility administrator.
2. Open **https://localhost/admin/abdm-sync**.
3. Find **ABDM delivery jobs**.
4. Select **pending**, **leased**, **done**, **dead** or **frozen** in **Delivery state**.
5. Click **Refresh jobs**; use pagination.
6. Read kind, attempts and safe error summary.
7. Do not click **Retry delivery** until the cause and current authority are checked.

This page is an **outbound queue**, not the incoming webhook inbox. Its separate legacy identity-link panel even warns about missing delivery monitoring; do not interpret that panel as an end-to-end tracker.
The doctor sees patient-specific results at **https://localhost/doctor/abdm**.

### D. Safe reachability check

```sh
curl --silent --show-error --dump-header - --output /dev/null \
  https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token
```

When the origin is healthy, expect **405** and `X-HealthDoc-Receipt-ID`.
It returned **502** during the 25 September outage, then **405** after the
app containers were rebound to existing files. Do not add `-k`.

When healthy, the public root and `/api/v1/health` intentionally return
**404**: the tunnel exposes only `/api/v3/**`. The recovered callback's **405**
proves that path reaches the app, not that NHA can deliver a real POST.
For local API health, open **https://localhost/api/v1/health**.

For a synthetic parser/route probe only:

```sh
docker exec healthdoc-backend-1 python -m scripts.probe_abdm_callback --base-url https://abdm.healthdoc.world
```

This sends dummy callbacks to your own server, not to NHA. Expected: missing-header **400** and wrapper-shaped unknown-operation **404**. It is not proof of a real linking-token delivery.

## 3. Which webhook corresponds to which step?

Prefix each path with **https://abdm.healthdoc.world**. These are POST destinations, not pages to open for a dashboard.

| Flow | Incoming path | What you should then check |
|---|---|---|
| M1 Scan-and-Share | `/api/v3/hip/patient/share` | Reception ticket and outgoing acknowledgement |
| M2 HIP token | `/api/v3/hip/token/on-generate-token` | Correlated pending link gains a usable token; never reveal it |
| M2 link confirmation | `/api/v3/link/on_carecontext` | Selected documents' link becomes confirmed |
| Context notification | `/api/v3/links/context/on-notify` | Notification acknowledgement, not clinical delivery |
| Deep-link SMS acknowledgement | `/api/v3/patients/sms/on-notify` | Corresponding notification outcome |
| PHR discovery | `/api/v3/hip/patient/care-context/discover` | Only that patient's eligible documents returned |
| PHR link-init | `/api/v3/hip/link/care-context/init` | Mediated OTP delivery prerequisite |
| PHR link-confirm | `/api/v3/hip/link/care-context/confirm` | Valid OTP confirmation and persisted linkage |
| M2 HIP consent | `/api/v3/consent/request/hip/notify` | Grant/revocation persisted and protocol acknowledgement sent |
| M2 HIP data request | `/api/v3/hip/health-information/request` | Authorized transfer job, encrypted delivery and notification |
| M3 consent initiation | `/api/v3/hiu/consent/request/on-init` | Gateway consent-request ID correlated |
| M3 status response | `/api/v3/hiu/consent/request/on-status` | Consent-request status updated |
| M3 consent decision | `/api/v3/hiu/consent/request/notify` | Patient decision; granted artefact fetched when appropriate |
| M3 artefact fetch | `/api/v3/hiu/consent/on-fetch` | Granted dates/types/expiry, not original requested scope |
| M3 data-request response | `/api/v3/hiu/health-information/on-request` | Transaction correlation |
| M3 encrypted data arrival | `/api/v3/hiu/health-information/transfer` | Pages validated, decrypted, stored and displayed to requester |

M1 OTP, identity verification and card/profile responses normally return through synchronous API calls: **do not wait for an on-generate-token webhook to verify an ABHA**. A HIP linking token and an M1 profile credential are different credentials.

## 4. Correct bridge/facility setup — do not use the pasted POST blindly

Your pasted example is incomplete. The supplied **PHR&HIECM.postman_collection 2.json** defines:

| Purpose | Method and full sandbox URL |
|---|---|
| Session | POST `https://dev.abdm.gov.in/api/hiecm/gateway/v3/sessions` |
| Read bridge/services | GET `https://dev.abdm.gov.in/api/hiecm/gateway/v3/bridge-services` |
| Read one service | GET `https://dev.abdm.gov.in/api/hiecm/gateway/v3/bridge-service/serviceId/{serviceId}` |
| Update callback base | PATCH `https://dev.abdm.gov.in/api/hiecm/gateway/v3/bridge/url` |
| Register/update service | **PUT** `https://dev.abdm.gov.in/api/hiecm/gateway/v3/bridge-service` |

Thus **POST /hiecm/gateway/v3/bridge-services** and an unspecified **/bridge/services** are not the write contract verified in this collection.
These are collection-verified contracts; the proposed new facility PUT has **not** been live-tested or submitted.

### Step 4.1 — verify the registry environment first

1. Open the portal on which you created the facility. Check its actual address bar against the links in your signed-in ABDM **sandbox** portal.
2. Confirm the facility card's ID, name, status and environment. “Submitted” is not the same as verified/approved.
3. Open **Software Linkage** on that card and inspect the existing association.
4. Confirm whether HealthDoc / IUI Solutions and your sandbox bridge are available in that environment. Follow the portal's authorized linkage procedure if required; do not link production registry data to a sandbox client by assumption.
5. Preserve a redacted screenshot of the domain, facility, service association and status.
6. Do not delete the existing HIP/HIU registrations. They are already active and existing records refer to them.

A gateway service registration, an HFR software association and a clinician registration are **three distinct things**.

### Step 4.2 — set up Postman without exposing secrets

1. Use the imported, credential-free [HealthDoc readiness collection](postman/healthdoc-abdm-readiness.postman_collection.json) and its [Postman instructions](postman/README.md). The supplied NHA collection is the contract reference, not a reason to import populated environment exports.
2. Use **Local Vault**, not Shared Vault or cloud-synced environment values, for credentials. Do not select the Production environment export.
3. The collection fixes the destination to `https://dev.abdm.gov.in` and client/bridge ID to `SBXID_053401`. Enter the existing secret directly into Local Vault as `healthdoc-abdm-client-secret`, restricted to that domain. Never paste the secret into this document.
4. Inspect inherited authorization and collection scripts before sending. Permit Vault access only to this reviewed collection and keep masking enabled. Do not share/export token-bearing console output.
5. For each *new logical operation*, generate a UUID REQUEST-ID and a current ISO UTC TIMESTAMP ending in Z. Keep the original ID for a deliberate retry of that same operation; do not assume NHA's duplicate-delivery semantics.
6. Use `X-CM-ID: sbx` and `Content-Type: application/json` for JSON. Arm the collection's `arm_session_once` variable to `yes`, then send **01 Session — manual arm and Local Vault required** with:
   `clientId`, `clientSecret`, `grantType: client_credentials`.
7. The script stores the access token in Local Vault as `healthdoc-abdm-access-token`; restrict it to the same domain. Gateway requests use `Authorization: Bearer {{vault:healthdoc-abdm-access-token}}`. Follow the response expiry rather than assuming every token lasts 1200 seconds. Do not save or share the raw session response.

Postman dynamic values you can use for a fresh request:
```text
REQUEST-ID: {{$guid}}
TIMESTAMP: {{$isoTimestamp}}
X-CM-ID: sbx
Content-Type: application/json
Authorization: Bearer {{vault:healthdoc-abdm-access-token}}
```

Dynamic REQUEST-ID regenerates on every send. Save/freeze the actual ID before a controlled same-operation retry.

### Step 4.3 — read before changing anything

Send **02 Read bridge and services**, then **03 Read IN0910034387**. Compare with:
- bridge URL: `https://abdm.healthdoc.world`;
- bridge ID: `SBXID_053401`;
- service ID: `IN0910034387`, name **HealthDoc Facility**;
- service `isHip`, `isHiu` and `active`: all **true**.

The old `SBXID_053401_HIP` and `SBXID_053401_HIU` entries also remain active.
They are historical/current-runtime identities, not substitutes for the corrected
facility. Preserve them until old operations and local configuration are reconciled.

If the callback URL already matches, **do not PATCH it**. Never replace it with webhook.site or a public capture URL; that would redirect real callbacks and possibly tokens/health information away from HealthDoc.

If correction is actually needed, the collection's **update-bridge-url** body is:
```json
{"url": "https://abdm.healthdoc.world"}
```
Use the PATCH path above. The base has **no /api/v3 suffix**; official callback paths contain that prefix.

### Step 4.4 — conditional facility service registration

**Skip this registration step for IN0910034387: it is already active as HIP and HIU.**
The template below is reference material for an approved future new service,
not a request to overwrite or duplicate today's confirmed registration.
Use **v3/gateway/bridge-service** (PUT), not the plural GET request.

Template for an approved HIP service, based on the collection:
```json
{
  "bridgeId": "SBXID_053401",
  "serviceId": "{{approved-hip-service-id}}",
  "name": "HealthDoc Test Hospital",
  "isHip": true,
  "isHiu": false,
  "isHealthLocker": null,
  "isPhr": false,
  "endpoints": {},
  "attributes": null,
  "active": true
}
```

Set `approved-hip-service-id` to the IN-number **only if** that association is confirmed for your sandbox setup. Do not send the literal placeholder.
Do not blindly change both existing roles into one new dual-role service; preserve the approved service topology. A HIU registration must also match the service used for HIU consent requests.
Read the service back after any successful write and retain the redacted result.

**Important local alignment gap:** on 25 September, `ABDM_HFR_FACILITY_ID`
and the development facility's `hfr_facility_id` were verified as
`IN0910034387`. The HIP/HIU sender IDs still use the old service IDs until
the 22 pending jobs for this facility are frozen using migration 0088 and the
count-checked procedure below. The other facility's pending job is outside
this cutover. Do not create a duplicate local facility, rewrite old clinical
authorship, or call the new IN-number integration finished before new
transactions and callbacks have been observed.

## 5. Bind your own doctor correctly

**Yes, HealthDoc can use your own authorized doctor. No, sending the administrator's HPID does not turn that account into a clinician.**

1. Obtain the participating doctor's permission, exact professional name and genuine registration evidence, or a documented NHA-approved sandbox requester identity.
2. Confirm the identifier **type**, **value** and issuing registry **URI** from the actual registry/assigned API contract. Do not infer them from an HPID's format.
3. If facility-professional association is needed, the facility portal has **Add Healthcare Professional**. Use the actual clinician's identity and authorized association procedure, not the manager's HPID.
4. In HealthDoc sign in as facility admin, open **https://localhost/admin/users**, and select/create that clinician's account with the doctor role in the correct facility.
5. Open **Profile** and fill:
   - **Full name** — actual professional name, not the hospital name;
   - **Registration number** — that clinician's actual identifier;
   - **ABDM registration identifier type** — exact approved vocabulary for it;
   - **Issuing registry URI** — actual issuer, not HealthDoc's callback URL.
6. Click **Save profile**. Confirm the account is active and belongs to this facility.
7. Sign in as that clinician and open **https://localhost/doctor/abdm**. The incomplete-requester warning should disappear when the four fields are complete.
8. This is a completeness check, **not automatic HPR verification**. Retain the identity/authority evidence separately.

Illustrative **shape only**, not values to send:
```json
{
  "requester": {
    "name": "<authorized clinician name>",
    "identifier": {
      "type": "<approved identifier type>",
      "value": "<that clinician's registration>",
      "system": "<actual issuing registry URI>"
    }
  }
}
```

The backend builds this from the signed-in staff profile. Do not bypass it by posting a different requester from Postman, borrow a public doctor's identity, or relabel historical `dev.doctor` records as a real clinician.
The reviewed M3 contract requires requester fields; it does **not** by itself establish that everyone must obtain a new HPR account. If no clinician is available, ask NHA for its approved sandbox requester policy and the four allowed fields.

## 6. Preflight before any patient action

1. Keep this Mac awake, Docker running, and the tunnel active throughout the exchange.
2. Open local HealthDoc and verify the correct patient and role. Log out when switching roles, or use separate browser profiles.
3. Confirm the sandbox participant is present, willing to receive OTPs and approve exactly the selected records in the **sandbox PHR app**.
4. Review current local consent in **https://localhost/consent**. Select the correct patient; record only the decision actually communicated, with accurate purpose/channel/expiry.
5. Local **Record consent** does **not** approve an ABDM PHR consent request. Those are separate actions.
6. Open the receipt inspector in one Terminal and admin jobs in a browser.
7. Check current queue metadata:
```sh
docker exec healthdoc-backend-1 python -m scripts.abdm_operational_status
docker exec healthdoc-backend-1 alembic current
```
8. Arrange controlled delivery per Appendix A before queuing M2/M3 work. **Do not start the general worker with the 23 old jobs unchecked.**
9. Use only approved synthetic clinical documents for this consenting sandbox participant. A real identity does not authorize inventing medical history.

## 7. M1 — identity, card and Scan-and-Share

### Existing ABHA verification

1. Sign in as receptionist and open **https://localhost/receptionist/registration**.
2. Search the existing patient by UHID/ABHA or name plus date of birth.
3. Click **Use this patient** on the correct match. Do not create another chart for the same ABHA.
4. In **ABHA identity**, choose **Use existing ABHA**.
5. Choose the intended method: **OTP to ABHA-linked mobile**, **OTP through Aadhaar**, **ABHA address**, or **Communication mobile**.
6. Enter the participant's own matching sandbox identifier. Click **Send OTP** once with their agreement.
7. Participant enters the OTP directly in the browser; click **Verify and link**. Never put OTPs in tickets/chat.
8. If account selection appears, select the exact participant account and click **Link selected account**.
9. Confirm **ABHA verified and linked** for the correct chart. Use **Download NHA ABHA card** if offered; the hospital UHID card is different.
10. Capture a redacted success screenshot and request IDs. Check that browser tokens/PHI are not in screenshots.

ABHA-address verification currently uses mobile OTP; it does not provide general auth-method discovery/address-Aadhaar selection.
Wrong/expired OTP: use the shown correction/resend controls and limits; don't repeatedly start fresh requests.
Old address-OTP attempts created before the 24 September API-family fix must be restarted.

### New ABHA creation — only for the assigned case and eligible participant

1. Search before registration; do not enrol someone merely to repeat a demo.
2. Select **Create ABHA**, have the participant review the displayed enrolment consent, then request the Aadhaar OTP with their authorization.
3. Complete Aadhaar verification.
4. If asked, complete **Send mobile OTP → Verify mobile** in the same enrolment session.
5. Select a suggested address and click **Save ABHA address**.
6. Verify the saved identity and download the NHA card.
7. Do not substitute a fabricated Aadhaar or accept consent on the participant's behalf.

### Scan-and-Share

1. Confirm the registered HIP and facility/counter QR configuration for this sandbox.
2. The participant scans the **ABDM facility QR** with the sandbox PHR app and deliberately shares their profile.
3. Check POST **/api/v3/hip/patient/share** in receipts.
4. Receptionist opens **https://localhost/receptionist/queue → ABDM Scan & Share**.
5. Find the reception ticket and complete the intended reception workflow.
6. Confirm the outgoing acknowledgement and patient-side token/result. A received profile alone is not the entire flow.
7. Confirm exact redelivery does not create a duplicate patient or ticket.

The QR printed on a local reception ticket is its ticket reference, **not automatically an ABDM facility QR**.
If you do not have the correctly configured facility QR, obtain it through the assigned sandbox procedure; do not encode the IN-number alone and assume compatibility.

M1 pass for a case means the assigned identity/card/Scan-and-Share outcome is observed. One OTP success does not pass all mandatory M1 cases.

## 8. M2 — publish, link and actually deliver records as HIP

1. With the authorized test clinician, finalize the approved synthetic record for the verified patient.
2. Open **https://localhost/doctor/abdm**. Enter the patient's name and date of birth, click **Search patients**, and select the correct chart.
3. Under **Share this facility's finalized documents**, confirm the intended document appears.
4. Each care context represents **one finalized document**, not the entire visit.
5. Select only authorized documents and click **Link selected documents** once.
6. Inspect the resulting new `link_token` job and deliver only that approved operation using Appendix A.
7. Wait for **/api/v3/hip/token/on-generate-token** with the matching original REQUEST-ID. A successful outbound job with no callback is not token success.
8. Confirm usable token metadata without reading or exporting the token. Process the correlated `link_context` job promptly; the current local use window is short (five-minute cap).
9. Wait for **/api/v3/link/on_carecontext**. Click **Refresh link status** and require **confirmed**.
10. In the participant's sandbox PHR app, check the correct facility and selected linked record.
11. Complete the PHR's authorized fetch/share flow: approve its exact consent, observe HIP consent notification and health-information request callbacks, and dispatch the scoped transfer/acknowledgement jobs.
12. Require the consumer/PHR to decrypt and display the correct clinical document. A link or encrypted HTTP push by itself is insufficient.
13. Verify context-notification acknowledgement if that case requires it.
14. Record the case ID, original request ID, callback receipt IDs, transaction ID and redacted PHR rendering.

If no token callback arrives, inspect receipts and edge logs first. Do not spam token generation, extend token lifetime, or call a second 202 proof of completion. Same-ID retry/deduplication behavior must be established, not guessed.

### Alternative PHR-initiated discovery/linking

The discover → init → confirm routes exist, but mediated OTP requires an approved SMS provider/HTTPS relay.
**You previously confirmed none is configured. This route remains blocked for live use until that is set up.**
Do not return an OTP in an HTTP response/log or bypass verification. Testing HIP-initiated linking does not silently waive a separate mandatory discovery case.

## 9. M3 — request, receive and review records as HIU

Prerequisites: authorized requester profile, verified ABHA, current patient consent, correctly registered HIU, and a source HIP with linked documents.
A HealthDoc-to-HealthDoc sandbox round trip can test plumbing, but external interoperability still needs the assigned external/NHA-supported source.

1. Sign in as the actual configured requester; open **https://localhost/doctor/abdm** and select the correct patient.
2. In **Request consent**, set **Records from**, **Records to**, and a future **Consent expires**.
3. Select only the required, supported record types. Current purpose is **care management (CAREMGT)**.
4. Click **Queue consent request** once and process its new `hiu_consent` job.
5. Check **/api/v3/hiu/consent/request/on-init** and the gateway consent-request correlation.
6. Participant opens the sandbox PHR consent request, checks requester/facility/types/dates/expiry, and chooses grant or denial themselves.
7. After grant, check **/api/v3/hiu/consent/request/notify** and **/api/v3/hiu/consent/on-fetch**; dispatch required acknowledgement/fetch jobs. In HealthDoc click **Refresh status** and require an actual **granted** artefact.
8. Click **Request consented records** for that artefact; process the new data-request job.
9. Check **/api/v3/hiu/health-information/on-request** and the transaction ID.
10. Wait for the source HIP's encrypted POST to **/api/v3/hiu/health-information/transfer**. This direct data push need not originate from NHA.
11. In **Consent and delivery**, check page counts, transfer outcome and record availability. Process receipt/notification jobs where queued.
12. Click **View record** as the original requesting clinician. Confirm patient, source HIP, date, record type and actual content.
13. Repeat a case where the participant grants a narrower date/type scope; only granted data may be requested/displayed.
14. Exercise denial, revocation and expiry. After revocation/expiry, a fresh read must refuse content, and scheduled cleanup must clear unusable keys/content. A label change alone is not enough.
15. Verify another patient/facility/unauthorized role cannot read the record.
16. Retain redacted end-to-end evidence and update the assigned workbook.

**Do not mark M3 complete unless decrypt/validate/store/render and refusal cases work.**
Today there are zero received-content rows; that is not a completed M3 exchange.

## 10. If something fails, stop at the right layer

| Observation | Next action |
|---|---|
| Public callback GET 502 | Restore local backend/nginx/tunnel; recheck localhost first |
| Public root/health GET 404 | Expected callback-only tunnel policy; use local health URL |
| Callback GET 405 with receipt | Routing works; now test the actual authorized POST flow |
| POST exists in edge log but no receipt | Correlate time/path, check middleware/receipt-storage errors and enabled configuration |
| No POST in local evidence | Check registered base, exact path, time window and tunnel; local absence alone cannot rule out edge rejection |
| 400/422 | Inspect redacted headers/body shape, current ISO UTC time, required IDs and original request correlation |
| 401/403 | Check actual endpoint authorization and sandbox service roles; never disable callback validation |
| `unknown_hip`/facility mismatch | Reconcile local HFR mapping and registered service IDs; do not rename IDs blindly |
| Job pending | Inspect safe reason, worker availability and prerequisites; refresh is not dispatch |
| Job done but link pending | Inspect token/link acknowledgement callbacks; outbound completion is not business confirmation |
| `link_not_found` | Confirm original request ID and pending operation; don't invent a link row |
| PHR consent never appears | Check on-init result, address/HIU association and dispatch; don't create many duplicate requests |
| Granted but no records | Check artefact, data job, source HIP, dataPushUrl and direct transfer receipt |
| Record received but unavailable | Check scope, expiry/revocation, requester, validation and decryption; don't bypass guards |

For support: exact sandbox endpoint, method, UTC time, REQUEST-ID/transaction ID, safe response status/code, callback path and redacted receipt evidence. Never include client secret, bearer/link token, OTP, Aadhaar, raw clinical bundle or private key.

## Appendix A. Delivery controls for the 24 September local snapshot

**Read this before clicking M2/M3 actions.**
Some callback handlers have a post-commit fast path, but the durable worker is
required for reliable recovery. The general worker was stopped in the 24
September snapshot; recheck its process and queue before dispatching any job.

### Corrected service-ID cutover — only for new tests

The owner approved using `IN0910034387` for **new** HIP/HIU tests while
preserving historical jobs for separate reconciliation. Migration 0088 adds a
non-dispatchable `frozen` state. Do this in order, with no participant activity:

1. Confirm the actual backend source mount and that no delivery worker is
   running. Stop any one-off `job_runner --mode all` process. Keep it off.
2. Back up the application PostgreSQL database to a private, access-controlled
   archive and verify `pg_restore --list` can read it. Do not publish the dump.
3. Deploy the reviewed migration and backend/frontend code, then run
   `alembic upgrade head` and verify revision `0088`. **Do not change sender
   IDs yet.**
4. Record a UTC cutoff before opening new participant activity. Run the exact
   facility-scoped dry-run below. The count `22` is the 25 September snapshot,
   not a permanent constant: re-query and stop on any mismatch. The script
   refuses leased jobs, a wrong HFR mapping, naive/future cutoff and a count
   mismatch.

```sh
docker exec healthdoc-backend-1 python -m scripts.freeze_abdm_jobs \
  --facility-id 00000000-0000-0000-0000-000000000101 \
  --expected-hfr-id IN0910034387 \
  --before REPLACE_WITH_RECORDED_UTC_ISO_TIMESTAMP \
  --expected-count 22
```

5. Only when the dry-run count is independently confirmed, repeat the same
   command with `--apply`. Check the admin jobs screen: these 22 should show
   under `frozen`, not `pending`; the unrelated facility's work is untouched.
6. Set the private runtime `ABDM_HIP_ID` and `ABDM_HIU_ID` to the registered
   `IN0910034387` service, recreate the backend with the **same reviewed
   source and private environment**, and verify its local health and public
   callback reachability. Never commit `.env` or print its secrets.
7. Create **fresh** authorized M1/M2/M3 transactions and verify each new
   outbound job, callback receipt and patient/clinician-visible result.
   Keep the historical frozen jobs frozen until individually reconciled; do
   not bulk retry or delete them. Starting continuous delivery remains a
   separate decision after queue inspection.

### Controlled single-job execution — operator only

1. Select the exact **new** job for the authorized current patient operation.
2. Inspect its kind, facility, target and current consent/identity; don't select a job merely because it is first in a list.
3. Obtain the UUID from the admin jobs API response (`/api/v1/abdm/operations/jobs`) in browser Network, without copying authorization headers. The current jobs list text does not show every internal target identifier; an engineer must verify target linkage before dispatch.
4. Replace the placeholder in this command. It can make an external call and is **not** a read-only check:

```sh
docker exec healthdoc-backend-1 python -c 'import asyncio, uuid; import app.main; from app.integrations.abdm.job_runner import run_once; print(asyncio.run(run_once(uuid.UUID("REPLACE_WITH_APPROVED_JOB_UUID"))))'
```

5. `True` means an attempt was claimed, **not** success. Recheck job status, safe error and business callback.
6. `False` means no eligible job was claimed. Do not reset leases or force state transitions.
7. Each follow-up job must be separately identified and authorized. Never loop over the entire pending queue. Respect available-at backoff.
8. Do not repeatedly replay a token-generation job when the outcome is unknown.

### Continuous delivery / cleanup

Before continuous delivery, an engineer must inspect the whole queue. The
25 September local snapshot had 22 pending jobs for the corrected facility
and one for a different facility. The first 22 may now be frozen as above;
the other facility's job is not covered by this cutover. There is no approved
bulk “cancel old queue” procedure; do not delete rows or mark them done.

Once the full queue is reconciled, a foreground worker using the **current running source** is:

```sh
docker exec -it healthdoc-backend-1 python -m app.integrations.abdm.job_runner --mode all
```

This performs external sends and cleanup; keep it running during the approved session. Ctrl-C stops it. API recreation also stops it. A reviewed persistent service from the same source/configuration is required for unattended operation.

For approved scheduled retention cleanup **without outbound dispatch**:
```sh
docker exec -it healthdoc-backend-1 python -m app.integrations.abdm.job_runner --mode cleanup
```

Cleanup deletes expired keys/content/receipts under implemented policies. Do not describe it as read-only or assume it is running just because the API is up.
There is no CLI `--mode callbacks` or delivery `--once` option; do not copy nonexistent flags.

## Appendix B. Do not accidentally switch back to the old source

On 26 September the running backend was mounted from the retained
`abdm-runtime-recovery-20260925` worktree, **not** the removed `/private/tmp`
paths in the earlier version of this guide. The specific source may change
after the cutover PR is deployed. Inspect the live container mount before
every restart and use only the reviewed source and its private runtime
configuration. A plain Compose command against a different checkout can
revert application code while retaining the same database.

Pause participant activity before a restart. Do not print or commit `.env`,
start an old worker override, delete a mounted worktree, or run database
tests against the application database. Existing backup archives have not
been restore-rehearsed; verify a fresh backup before migration 0088.

## Appendix C. What cannot be finished by filling in IDs alone

- Verify the new facility's environment/software association and align its local HFR mapping.
- Supply an authorized clinician requester, not the facility manager's HPID.
- Reconcile the historical queue and run reliable delivery/retention workers.
- Obtain a successful real token callback, confirmed document link and patient-side rendering.
- Complete real consent → encrypted transfer → decryption → requester-visible M3 evidence.
- Add an approved SMS provider for mediated PHR discovery/linking if required by the assigned cases.
- Validate the assigned HI-type scope. Existing exporters cover **OPConsultation, Prescription, DiagnosticReport, DischargeSummary and WellnessRecord**; this tranche does not add **ImmunizationRecord, HealthDocumentRecord or Invoice**.
- Complete remaining M1 method-selection/assigned-case coverage. Existing card/OTP UI is not proof every workbook row passes.
- Resolve the long-lived linking-credential reuse/retention design if required; do not extend the five-minute cap just to suppress an error.
- Measure real callback-to-acknowledgement latency, including recovery/backlog.
- Complete NHA evaluation/submission. Engineering success is not self-issued certification.

## Appendix D. Evidence checklist and sources

For **each assigned case**, record:
```text
Workbook + case ID:
Application revision / local uncommitted-fix description:
Environment / operator role:
UTC time:
Original REQUEST-ID:
Callback receipt ID(s):
Consent / transaction ID (where applicable):
Expected result:
Observed server state:
Observed PHR / clinician-screen result:
Outcome: PASS / FAIL / BLOCKED / NOT RUN
Redacted evidence location:
Remaining action / owner:
```

Do not put participant identifiers or secrets in a public Git report. Screenshot only the minimum necessary and redact patient details.

Sources checked:
1. Local supplied `Postman collections from ABDM/PHR&HIECM.postman_collection 2.json`: **Gateway** and **Session-token** requests. Source of the exact GET/PUT/PATCH contracts above; no facility PUT was executed for this guide.
2. Supplied M1 collection `Milestone_1_Postman_Collection_18_08_2025_postman_collection_d202ddf09a.json` and Scan-and-Share collection.
3. Supplied `ABDM DOCS/M2_Document_16_02_2026_11822aedc7.docx`, `M3_Dcoument_16_02_2026_2319bac7bf.docx` and the M1/M2/M3 XLSX workbooks. Follow the specific cases assigned to HealthDoc, not an assumed generic subset.
4. [NHA callback path constants](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/common/constants/GatewayURL.java). The direct transfer URL is HealthDoc's advertised receiving endpoint.
5. [Official sandbox documentation](https://sandbox.abdm.gov.in/sandbox/v3/new-documentation?doc=WorkingWithABDMapi). Automated reading returned 403; use the signed-in portal to verify current assigned guidance.
6. HealthDoc source: `external_router.py`, `hiu/requester.py`, `job_runner.py`, receipt/status scripts, receptionist ABHA panel, doctor ABDM workspace and admin profile/jobs UI.
7. [Detailed repair evidence](abdm-m1-contract-callback-fixes-2026-09-24.md), [callback diagnostics](abdm-callback-diagnostics-2026-09-14.md), and [case ledger](abdm-milestone-case-ledger-2026-09-10.md).

This file contains procedures and observed status. Writing it did not register a new service, alter a clinician, send an OTP, grant consent, dispatch old jobs or transfer clinical data.
