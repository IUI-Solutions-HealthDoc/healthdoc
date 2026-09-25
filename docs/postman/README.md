# HealthDoc Postman readiness pack — updated 25 September 2026

The collection is a non-clinical readiness aid, not an M1–M3 certification
collection. On 25 September, the public callback probe returned **502** and
`https://localhost/api/v1/health` was unreachable. Restore the local
backend/nginx/tunnel before repeating callback checks or any milestone flow.

## Correct facility and verified response

**IN0910034387 — HealthDoc Facility** supersedes the earlier incorrect IN0911638718.
The owner's corrected screenshot shows **hspsbx.abdm.gov.in** software linkage
to bridge **SBXID_053401**, URL **https://abdm.healthdoc.world**.

Independent live **backend** readback, not Postman evidence:
- GET `/api/hiecm/gateway/v3/bridge-services` → **200**,
  REQUEST-ID `d1b298c4-bf8d-45d5-a5d2-3ac0d1b86761`.
- GET `/api/hiecm/gateway/v3/bridge-service/serviceId/IN0910034387` → **200**,
  REQUEST-ID `1d9c247f-5b4d-4689-b15f-9a131b4a3438`.

Relevant allowlisted service-response excerpt:
```json
{
  "bridgeId": "SBXID_053401",
  "serviceId": "IN0910034387",
  "name": "HealthDoc Facility",
  "isHip": true,
  "isHiu": true,
  "active": true
}
```

No service registration was changed. **Do not re-register this service.**
The old HIP/HIU entries still exist; reconcile their historical operations
before changing application identity.

The new HPID is masked, ending 6184, and the screenshot's professional/council
application is **Draft**. Do not guess the full number or treat registration
completeness as verified clinician authority.

## Local identity mismatch — last inspected before runtime outage

| Setting | Last inspected local configuration | Correct registered service to plan against |
|---|---|---|
| ABDM_HIP_ID | SBXID_053401_HIP | IN0910034387 |
| ABDM_HIU_ID | SBXID_053401_HIU | IN0910034387 |
| ABDM_HFR_FACILITY_ID | SBXID_053401_HIP | IN0910034387 |

The local facility row also used the old HFR value at the last inspection. A backed-up, coordinated
configuration/facility update and old-job reconciliation are required.
Changing a Postman request does not update HealthDoc. No local identity
switch, clinician-profile write or historical-row rewrite was performed.

## Imported collection

[healthdoc-abdm-readiness.postman_collection.json](healthdoc-abdm-readiness.postman_collection.json)

The user completed the import into Postman. The collection contains **21**
requests, no credentials, no participant identifiers and no saved response examples.
Do not import .env files, populated ABDM environment exports or the project root.

- **00 Public callback routing**: 16 GET checks; once the server is healthy,
  expect **405 + receipt UUID**. A current 502 is an infrastructure failure.
- **01 Synthetic header validation**: dummy POST `{}` to your own callback,
  expect **400 + receipt UUID**. Does not ask NHA for a token.
- **02 NHA registration**: one separately armed session and two authenticated GETs.
- **03 Local API**: local health, expect 200 after trusting the approved certificate.

Only run the relevant folder/request. Running the whole readiness collection
does not establish milestone acceptance. Do not let Postman AI change a GET
probe to POST merely because the intentional response is 405.

## Local Vault and session — user enters secret

The user explicitly approved **Local Vault, session and GET checks only**.
That does not authorize OTPs, clinical transmissions or registry writes.

1. Click **Vault**; use **Local Vault**, not Shared Vault.
2. Add **healthdoc-abdm-client-secret**, enter the existing sandbox secret
   privately, and restrict its allowed domain to **dev.abdm.gov.in**.
3. The session script populates **healthdoc-abdm-access-token** in Local Vault.
   Apply the same domain restriction to that token. Keep masking on.
4. Review scripts and permit Local Vault script access only for this collection,
   not arbitrary workspace scripts. Never paste secrets into Postman AI.
5. Open the collection's **Variables**, set **arm_session_once** to **yes**
   immediately before the intended send. It resets to **no**.
6. Open **01 Session — manual arm and Local Vault required**, click **Send**.
7. Require HTTP **200**, a token and positive expiry; check **Test Results**.
   The script stores the access token in Local Vault without console logging
   or environment persistence.
8. The raw response contains credentials: **do not save as an example,
   screenshot its body, or share it**. Show status/test results only.
9. Send **02 Read bridge and services**, then **03 Read IN0910034387**.
10. Require actual 200 responses, correct bridge/service/base URL and
    **isHip/isHiu/active all true**.
11. For NHA evidence show method, URL, non-secret REQUEST-ID/TIMESTAMP,
    HTTP status, safe response and test result. Hide Authorization.
12. If a token expires, deliberately obtain one new session; do not loop.

Unarmed or unavailable-Vault requests are **skipped, not passed**. Do not
remove the guard to fix a missing secret. Keep TLS verification enabled;
browser certificate acceptance does not automatically configure Postman's trust.

Official sources:
[Local Vault](https://learning.postman.com/docs/use/postman-vault/use-vault-secrets),
[script access](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-vault/).

## Incoming webhook evidence

Postman is a sender, **not HealthDoc's incoming webhook inbox**. Do not move
the registered bridge URL to a public Postman/webhook capture endpoint.

```sh
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --limit 20
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --request-id ORIGINAL_REQUEST_UUID
docker exec healthdoc-backend-1 python -m scripts.abdm_callback_receipts --id RECEIPT_UUID --details
```

Correlate Postman's **X-HealthDoc-Receipt-ID** with the private inspector.
For actual workflows also correlate the original outbound REQUEST-ID.
Synthetic GET/invalid-POST receipts are not successful M2/M3 evidence.

## Observed results so far

| Check | Observed result |
|---|---|
| NHA new-service registration | Two independent backend GETs passed, as recorded above |
| Postman import | Completed by user; imported collection visible |
| Postman M2 token callback GET | Passed with **405 + receipt ID** on 24 September; the public endpoint returned **502** on 25 September |
| Remaining Postman callback probes | Not yet run in Postman |
| Local Vault | Client-secret entry and allowed domain now visible; secret value not inspected |
| Postman session/registration GETs | Session and both read-only registration GETs previously returned **200** after the user configured Local Vault; retain a fresh redacted run for milestone evidence |
| Local health in Postman | Not currently testable: local HTTPS port 443 was unreachable on 25 September |
| M1/M2/M3 acceptance | Not established by these readiness checks |

## Actual clinical workflows

Use the [self-service runbook](../abdm-self-service-webhooks-m1-m2-m3-2026-09-24.md).
M1 needs participant consent/OTP. M2 callback handling needs a persisted,
correlated HealthDoc linking operation. M3 needs an authorized requester,
patient-approved artefact and persisted private transfer keys.

Do not send raw NHA token/health-information examples independently and then
invent pending database rows when their callbacks fail correlation.
A reviewed Postman milestone workflow must preserve the application's
operation state. No actual patient/link/consent calls are included in this
readiness pack.

## Offline collection regression check

```sh
node docs/postman/validate-collection.mjs
```

Passed for **21 requests / 42 scripts**, including destination guards,
one-shot session arming, refusal without Vault access, token validation and
negative mutations of callback receipts and service-registration assertions.
This test performs no network requests and is not live Postman or milestone evidence.
