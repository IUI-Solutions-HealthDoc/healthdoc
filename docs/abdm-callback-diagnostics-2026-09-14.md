# ABDM callback receiver diagnostics — 14 September 2026

## Scope and evidence boundary

This change tests the receiver contract and makes new callback failures
inspectable. It does not generate an NHA token, replay a real participant's
operation, transmit clinical data, prove gateway origin or complete M2/M3.
No Cloudflare Worker, bridge change or relaxed callback authorization is used.

The wrapper's `OnGenerateTokenResponse` fields are `abhaAddress`, `linkToken`,
`response` and `error`; `LinkTokenResponse` additionally permits `entity`.
Both use nested `response.requestId`. Sources:

- [NHA OnGenerateTokenResponse](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/hip/hrp/link/hipInitiated/responses/OnGenerateTokenResponse.java)
- [NHA LinkTokenResponse](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v3/hip/hrp/link/hipInitiated/responses/LinkTokenResponse.java)
- Supplied `ABDM DOCS/M2_Document_16_02_2026_11822aedc7.docx`, §§4.3.1–4.3.2.

The local HTTPS unknown-operation probe returned **404**, not 400. The isolated
HTTP regression accepts **both** wrapper shapes with 202 for a synthetic pending
operation, refuses an unknown operation with 404 and wrong patient with 422.
Callback routing dependencies are real in that test; database, Redis and outbound
calls are isolated test doubles. This is not a real gateway callback replay.

## Implemented diagnostics

### Persistent origin access logs

- nginx records bounded, escaped `CF-Connecting-IP` and `X-Forwarded-For`
  **claims**, alongside its observed client address and our generated receipt ID.
  These headers can be spoofed on a directly reachable origin. They are not
  authentication and must not become an IP allowlist without trusted-hop design.
- Query strings and referrers are excluded; OAuth codes and patient searches
  must not enter the new access records. No request body or authorization header
  is added to nginx logs.
- Daily access files live in `nginx-logs:/var/log/healthdoc`, a private 0700
  directory, in both development and production Compose. Container replacement
  preserves this named volume. `down -v` or explicit volume deletion does not.
- An entrypoint task prunes only `access-YYYY-MM-DD.log` files older than the
  seven-day operational window, hourly while nginx runs. Existing stderr access
  logging remains for normal container troubleshooting.
- The explicit `/usr/share/nginx/html` root exists in the image. nginx checks
  this even for proxied requests before writing variable-path log files; its
  compiled default `/etc/nginx/html` is absent. See the
  [nginx access-log constraints](https://nginx.org/en/docs/http/ngx_http_log_module.html#access_log).
- nginx errors and general backend stdout/stderr remain Docker logs, not the
  persistent access volume. `scripts/maintenance/archive_callback_logs.py`
  preserves the two existing containers' logs privately before recreation.
  Historical archives may contain sensitive information: never attach them raw.

### Durable callback receipts

Migration **0073** creates `abdm_callback_receipts`. An independent transaction
stores an initial receipt before the handler, then records its outcome afterward.
A clinical transaction rollback therefore cannot erase the observed refusal.
An incomplete receipt remains identifiable when a process dies between writes.

Stored metadata: generated receipt ID, validated inbound REQUEST-ID, nested
response correlation UUID, known route, method, HTTP status, received/completed
times, byte count and expiry. `X-HealthDoc-Receipt-ID` ties HTTP responses and
nginx access records to this row.

Headers, source-IP claims and request/response **redacted structural snapshots**
are encrypted with AES-GCM and row-bound associated data. There is no plaintext
copy in logs. Capture is limited to 16 KiB per request/response, with depth,
field, list and node limits. Oversized, malformed or incomplete bodies are marked
as such, not retained as raw fragments.

Retained: known field names, value types, UUID correlations, documented/allowlisted
error codes, validation locations/types, timestamp validity and routing-header
presence. Removed: bearer/link tokens, OTPs, ABHA numbers/addresses, demographics,
clinical scalar values, key material, unknown header values and unknown field
names. Even an input field called `Authorization` or a response echo cannot
introduce a plaintext credential into the snapshot. This is intentionally **not
byte-for-byte payload logging**.

Receipts expire after seven days and the cleanup-only worker deletes expired rows.
The inspector refuses expired records even before physical cleanup. This policy
is for debugging—not a declaration about legal clinical/audit retention. Backups
and any manually exported evidence need their own approved retention policy.
The local cleanup-only service is deployed separately. Production operators must
also schedule that mode; the base production Compose file alone does not start an
ABDM worker or guarantee physical expiry processing.

Storage failure does not replace the clinical response. It increments
`abdm_callback_evidence_failures_total` and logs the receipt ID without SQL
parameters or exception bodies. A Prometheus alert rule covers this failure.
Alert delivery still requires the deployed monitoring stack and receiver.

No web endpoint exposes this deployment-wide untrusted inbox. The read-only CLI
requires existing local operator database/crypto access; ordinary facility users
cannot enumerate another facility's rejected callbacks.

## Use

1. Back up the local database and archive current logs before recreation.
2. Apply `alembic upgrade head` (0073). Enable `ABDM_CALLBACK_EVIDENCE_ENABLED=true`;
   Compose supplies it after an upgraded deployment. Settings default false for
   non-Compose/test consumers to avoid silently connecting their mock app to a
   real receipt database.
3. Recreate backend and nginx using the existing Compose stack, without starting
   the outbound delivery worker. The cleanup-only service must stay running.
4. Inspect metadata inside the backend container:

   ```sh
   python -m scripts.abdm_callback_receipts --limit 20
   python -m scripts.abdm_callback_receipts --request-id CORRELATION_UUID
   python -m scripts.abdm_callback_receipts --id RECEIPT_UUID --details
   ```

   `--details` requires one exact receipt ID and decrypts only the redacted
   snapshot. IP claims are private operational data; do not paste them into a PR.

5. Repeat synthetic probes with TLS verification, from a configured Python runtime:

   ```sh
   # Run from backend; provide the configured non-secret ABDM_HIP_ID in environment.
   python -m scripts.probe_abdm_callback --base-url https://localhost \
     --ca-cert ../infra/nginx/certs/dev.crt
   python -m scripts.probe_abdm_callback --base-url https://abdm.healthdoc.world
   ```

   The command uses fresh synthetic identities/correlations, accepts no patient
   or operation input, and refuses redirects. Expected results: missing routing
   headers → 400; wrapper-shaped body with unknown operation → 404. It makes
   no request to `dev.abdm.gov.in` and consumes no NHA token-generation quota.

## Remaining boundaries

- A forged/local probe is not an authenticated NHA transaction. The milestone
  case ledger must still show real gateway/PHR consent and transfer outcomes.
- Receipts observe requests that reach the application. nginx-level 413/429 or
  unavailable-backend 502 responses have access logs but no application receipt.
- Requests rejected by Cloudflare/WAF or a tunnel ingress catchall before nginx
  remain outside origin visibility. Adding origin logging cannot reconstruct
  the deleted 11 September container window or prove NHA never attempted delivery.
- Do not change the registered base to add `/api`: the supplied callback path
  already appends `/api/v3/hip/token/on-generate-token`.
- A fresh callback body may still fail correlation, patient match, expiry or
  header checks. Its exact safe rejection code is now inspectable; do not loosen
  those checks just to obtain a 202.

## Execution record

- Local database backup: `backups/abdm-0073-20260914/healthdoc_healthdoc_20260914T062208Z.dump`;
  custom-format dump readable by `pg_restore --list` (not a full restore rehearsal).
- Previous nginx/backend container logs archived privately under that directory.
- Migration 0073 applied to local development and test databases.
- Targeted PostgreSQL-backed gate: **121 passed**, including independent-connection
  rollback survival. Two existing Pydantic alias warnings remain.
- Full gate after the test-fixture correction: **1,929 backend + 36 script tests
  passed**; migration integrity passed, head 0073. Six existing Pydantic warnings
  and 16 convention-check warnings remain (zero blockers). Explicit new-source
  convention and Ruff checks passed. A six-hex-character facility fixture code
  collided with a retained test row; both files-suite fixtures now use 16 hex
  characters. No database clearing or test retries were added.
- nginx syntax and persistent-volume entrypoint initialization passed in a
  disposable container. The three nginx regressions passed again after correcting
  the image document root.
- Backend, nginx and cleanup-only containers were recreated locally. The general
  outbound worker remains stopped. Callback capture reports enabled.
- **Live local and public HTTPS probes passed**, with certificate verification:

  | Receiver | Missing headers | Wrapper-shaped unknown operation |
  |---|---|---|
  | `https://localhost` | 400 `missing_abdm_headers` | 404 `link_not_found` |
  | `https://abdm.healthdoc.world` | 400 `missing_abdm_headers` | 404 `link_not_found` |

  Local receipt IDs: `bd076703-fb97-4bda-a10a-49452dd56800`,
  `7c6c1f0e-4e5f-4629-b66a-9f8c6a1a9931`. Public receipt IDs:
  `732bafc8-3543-4393-b114-6150bdad5857`,
  `91fb8589-6a03-473f-a9bd-0e65641a74ee`. All are **synthetic receiver probes**,
  not NHA milestone transactions.
- Both local receipts were read back from PostgreSQL: completed status, redacted
  parsed body and safe error evidence retained; synthetic token/address values
  absent. nginx's dated volume file exists and is nonempty inside its private
  0700 directory.
- Cross-layer correlation, public receipt detail checks and a second recreation
  persistence check remain pending below; do not infer them from file existence.
  The tool approval service repeatedly failed with **selected model at capacity**
  on the read-only correlation command. No rejected command was bypassed and no
  second recreation was attempted. This is a verification blocker, not an HTTP
  failure observed from HealthDoc.

### Resume the last verification

1. Read the four exact synthetic receipt IDs above using the operator inspector;
   verify completed 400/404 outcomes and redaction. Check the public receipts'
   forwarded-IP claim presence without exporting the addresses.
2. Confirm each exact receipt ID appears once in
   `/var/log/healthdoc/access-2026-09-14.log`. Do not paste raw access lines into
   a ticket or PR.
3. Archive current Docker logs to a new private directory, then recreate only
   backend/nginx with the existing Compose command and retained named volumes.
   Expect a brief local interruption. Do not use `down -v`, remove orphans, or
   start the general ABDM worker.
4. Repeat steps 1–2 against the same original IDs, and repeat the TLS-verified
   synthetic probes with fresh IDs. This proves old evidence survived and new
   capture continues after replacement. Record the result, not just `Up` status.
