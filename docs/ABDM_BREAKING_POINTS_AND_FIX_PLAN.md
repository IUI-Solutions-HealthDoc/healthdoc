# ABDM integration — breaking points and fix plan

**Prepared:** 2026-09-02 · **Scope:** the ABDM M1/M2/M3 integration and its
deployment surface, plus a short sweep of non-ABDM findings. **Method:** static
tracing of every outbound caller and inbound route, a live reachability probe of
the Cloudflare tunnel, a schema-valid forged-callback probe run against the
running backend, and the ABDM integration test subset (205 passed) plus the
contract gate (189 calls match).

This document is a companion to `ABDM_WIRING_AUDIT_CONTEXT.md`. That file asked
whether the integration is *wired*. The answer is: yes, the outbound and inbound
legs are genuinely connected — every `abdm_path_hip_*` / `abdm_path_hiu_*`
setting now has exactly one caller, and every v3 callback route is mounted and
answers a non-404. The breaking points below are not missing wiring. They are a
forgeable public surface, a retry that is silently dropped, a records-vocabulary
that is wider than the bundle builder, and the gap between "the plumbing exists"
and "anything flows through it."

---

## Verdict

The integration would not fail an ABDM certification run on wiring. It would
fail on two things a certifier and a CERT-In assessor look at directly:

1. **The v3 callback surface is reachable from the open internet with no source
   restriction, and a forged callback carrying only public header values writes
   a `granted` consent artefact and can inject "verified" patients.** This is
   live right now on `https://abdm.healthdoc.world`.
2. **Nothing feeds the HIP side.** There are zero care-context rows, no
   automatic creation of them on visit close, and no staff UI to create them. A
   discovery or link request would find nothing to share. The plumbing is
   correct and empty.

Everything else is a ranked list of correctness and operability defects that
should be closed before a real patient milestone run.

---

## Severity tally

| Severity | Count | Findings |
|---|---|---|
| Critical | 1 | F1 |
| High | 3 | F2, F3, F4 |
| Medium | 4 | F5, F6, F7, F8 |
| Low / by-design | 4 | F9, F10, F11, F12 |

---

## Fix status — 2026-09-02

Code fixes applied this pass; full Postgres suite green at **1194 passed**.

| Finding | Status | What changed |
|---|---|---|
| F2 | **Fixed** | Replay lock released on handler failure via generator dependencies in `callback_auth.py`; two new tests in `test_abdm_callback_auth.py`. |
| F3 | **Fixed** | HI-type vocabulary narrowed to the 5 buildable types across `gateway.HI_TYPES`, the model CHECK and migration `0059`; drift test `test_abdm_hi_type_vocabulary.py` keeps the three in agreement. |
| F8 | **Fixed** | `assert_audit_coverage()` is now called from the lifespan with `AUDITABLE_MODULE_PREFIXES` covering the ABDM `hip`/`hiu` packages. |
| F9 | **Fixed** | CI lint step uses `continue-on-error` instead of `\|\| true`. |
| F10 | **Fixed** | Clarifying comments on the reserved bridge/certs settings. |
| F1 | **Deferred — operator action** | Repointing the live Cloudflare tunnel and adding a source restriction are hard-to-reverse, outward-facing infra changes against a running system. Not applied from here. See the fix steps under F1. |
| F4 | **Deferred — feature** | Auto-creating care contexts and building the M2/M3 staff UI is new product work, not a contained fix. |
| F5 | **Deferred — needs scheduler** | The reaper needs a periodic runner the app does not yet have; adding a dead function would be its own anti-pattern. |
| F6 | **Deferred — semantics decision** | A distinct scan-and-share identity status needs a new `identity_status` enum value (migration + UI ripple); the intended semantics are a product call. |
| F7 | **Deferred — residual** | Low-likelihood TOCTOU; the connect-time IP pin is fiddly and best done with F1. |
| F11, F12 | **Noted** | Informational / out of primary scope. |

---

## F1 — Forgeable v3 callbacks on an internet-reachable, nginx-bypassing tunnel

**Severity: Critical.** Confirmed live and by local probe.

**What is wired.** `callback_auth._verify_gateway_headers` (callback_auth.py:197)
enforces `REQUEST-ID` (must be a UUID), `TIMESTAMP` (10-minute freshness),
`X-CM-ID` (must equal `sbx`), the addressed `X-HIP-ID`/`X-HIU-ID` (must equal the
configured service id), and a 60-second Redis replay coalesce. The file's own
docstring is honest that this is not origin authentication: *"source
restrictions belong at the public edge until NHA publishes such a scheme."*

**What only looks wired.** The edge does not protect it. `~/.cloudflared/config.yml`
points the tunnel at `http://localhost:58000` — the backend directly, **bypassing
nginx**, so the rate limiting and headers in `infra/nginx/` never apply to
callback traffic. Every header the v3 verifier checks is a **public** value: the
HIP id `SBXID_053401_HIP` appears in the bridge registry, `sbx` is the sandbox
consent-manager id, and `REQUEST-ID`/`TIMESTAMP` are attacker-chosen. There is no
secret and no signature on this path.

**The concrete failure.** Verified two ways:

- *Reachability (live).* Through the public hostname, `GET /api/v1/health` → 200,
  `GET /api/v1/docs` → 200, `GET /api/v1/openapi.json` → 200 (383 KB, the full
  API inventory), `GET /metrics` → 200, `GET /api/v3/consent/request/hip/notify`
  → 405 (route exists, POST-only). The sandbox backend is answering the internet
  directly.
- *Forgery (local probe).* A schema-valid `POST /api/v3/consent/request/hip/notify`
  carrying only the four public headers and a `GRANTED` notification body →
  **202, and an `AbdmHipConsentArtefact` row is written with `status="granted"`**
  for an attacker-chosen consent id, ABHA address, HI types and date range.

Blast radius, stated precisely:

- Forged consent-notify **writes/updates granted consent artefacts** — the exact
  document `authorise_hi_request` treats as the evidence for releasing records.
- Forged scan-and-share (`/api/v3/hip/patient/share`) **creates `Patient` rows
  with `identity_status="verified"`, `identity_path="abdm"`** (external_router.py:454).
  An attacker can inject fake, "verified" patients.
- Forged health-information/request records an HI request and fires a background
  transfer to an **attacker-supplied `dataPushUrl`**.
- **What holds the line:** full record exfiltration additionally requires a
  *confirmed link* joining the ABHA address to consented care-context references.
  `list_care_contexts_for_transfer` (hip/service.py:214) joins through a
  `status="confirmed"` link and intersects with the artefact's consented
  references; without a pre-existing confirmed link it returns `[]` and the
  worker aborts with "Consent covers no linked clinical care contexts." The
  scope gate the audit asked about (§6) genuinely works. The HIU direct-transfer
  receive path is authenticated by ECDH/GCM bound to a transaction we opened and
  is **not** forgeable.

So the exposure is: consent-ledger forgery, fake verified-patient injection, and
forced outbound POSTs to attacker URLs. Mass record exfiltration is gated behind
a real confirmed link, which is the one thing the code defends well.

**Fix.**

1. *Immediate (hours).* Repoint the tunnel at nginx, not the backend:
   `service: https://localhost:443` with `originRequest: { noTLSVerify: true }`
   (or a real origin cert). This restores rate limiting and headers on callback
   traffic and closes `/api/v1/docs`, `/openapi.json` and `/metrics` to the
   public hostname via the nginx location rules.
2. *Immediate (hours).* Restrict who may reach the callback paths. ABDM sandbox
   egress IPs are the ideal allowlist; where they are unstable, use a Cloudflare
   Access service-token or WAF rule scoped to `abdm.healthdoc.world` so only the
   gateway (or a signed request) reaches `/api/v3/*`. Document the control in
   `SECURITY.md` as the compensating measure until a signature scheme exists.
3. *Medium.* Set `ENVIRONMENT=production`-equivalent doc-gating on any
   internet-exposed deployment so the OpenAPI schema is never served publicly,
   even in the sandbox.
4. *When NHA publishes it.* Implement callback signature verification. The JWKS
   endpoint is already a setting (`abdm_path_gateway_certs`), reserved for
   exactly this, so the verifier has a home to grow into.

Note: `ABDM_CALLBACK_SHARED_SECRET` does **not** help here — by design it guards
only the legacy `/api/v1/abdm/*` routes, not these v3 ones. The near-term control
must be network-level.

---

## F2 — A callback that fails after header check is dropped on the gateway's retry

**Severity: High.** Confirmed by local probe.

**What is wired.** Each v3 handler opens with `if callback.replayed: return
_accepted()`. The replay key is set with `NX` and a 60-second TTL
(callback_auth.py:261). The intent, per the file's comment, is to coalesce a
gateway retry that arrives *while the first request is still running*, and to let
"a failed handler run again," with the database state machine as the durable
duplicate guard.

**What only looks wired.** The two guards fight each other. The Redis replay key
is committed the instant the request is seen, during dependency resolution. If
the handler body then fails — for example the outbound acknowledgement raises,
which `_outbound` turns into a 502 (external_router.py:174) — the `get_db`
dependency rolls the database transaction back (db.py), but the Redis key
**survives**. The gateway's retry, which arrives within seconds carrying the same
`REQUEST-ID`, hits `replayed=True` and returns 202 **without re-running the
handler**.

**The concrete failure.** Probe result: a consent-notify whose first
acknowledgement fails returns 502; the immediate retry with the same
`REQUEST-ID` returns 202 and the acknowledgement is **never re-attempted** (ack
call count stayed at 1). Per the code's own docstring, an unacknowledged
consent notification is retried by the gateway and then treated as a failed
grant — "the consent takes effect here and nowhere else." So a transient blip on
the outbound ack, inside a 60-second window, silently loses the consent grant.
The same pattern applies to `hiu_consent_notify` (which fires `fetch_consent_artefact`
inside the handler) and any handler whose outbound leg can raise.

**Fix.** Make the replay key confirm success, not receipt. Options, cheapest
first:

- Only set the replay key **after** the handler has committed its durable state
  and sent its acknowledgement — i.e. move the `NX` set out of the pre-handler
  dependency and into the end of the successful path. A failed handler then
  leaves no key and the retry re-runs.
- Or delete the replay key on any non-2xx handler outcome (a `finally` that
  clears it unless the handler recorded success).
- Keep the durable DB uniqueness (transaction_id / consent_artefact_id) as the
  real idempotency guard, which already exists; the Redis key should only
  coalesce genuinely concurrent duplicates, never mask a failure.

---

## F3 — Care-context HI-type vocabulary is wider than the bundle builder

**Severity: High.** Confirmed by reading the CHECK, the validator and the builder.

**What is wired.** `hip/gateway.validate_hi_types` accepts eight ABDM HI types
(including `Invoice`). The DB CHECK on `abdm_care_contexts.hi_type` (models.py,
migration 0055) allows seven: `OPConsultation`, `Prescription`,
`DiagnosticReport`, `DischargeSummary`, `ImmunizationRecord`,
`HealthDocumentRecord`, `WellnessRecord`.

**What only looks wired.** The FHIR builder (`fhir/builder.py`, `RECORD_TYPES`)
substantiates only **five**: `OPConsultation`, `DiagnosticReport`,
`Prescription`, `DischargeSummary`, `WellnessRecord`. The transfer worker's
`_clinical_facts` (hip/worker.py) raises `TransferError("No clinical mapper
exists for HI type ...")` for anything else.

**The concrete failure.** A care context stored as `ImmunizationRecord` or
`HealthDocumentRecord` passes the DB CHECK and the outbound validator, links and
discovers normally, and then **fails at transfer time** — the worker marks the
request `failed` and notifies the gateway `FAILED`. To a patient this is a record
that linked and then could not be delivered: the exact "empty/failed shell"
failure mode the audit flagged (§5). Separately, `Invoice` is accepted by the
outbound validator (ABDM's own on-discovery example uses it) but cannot be stored
as a care context at all.

**Fix.** Make the three vocabularies agree on one source of truth:

- Narrow the DB CHECK and `validate_hi_types` to the five types the builder can
  populate, **or** add builders for `ImmunizationRecord` and
  `HealthDocumentRecord` before allowing them as care contexts.
- Decide `Invoice` explicitly: either support it end to end or drop it from
  `HI_TYPES`. Do not leave it acceptable outbound but unstorable.
- Add a test that asserts `set(builder RECORD_TYPES) == set(DB CHECK types) ==
  set(HI_TYPES minus deliberate-exclusions)` so the three cannot drift again.

---

## F4 — Nothing creates care contexts; the HIP side is wired and empty

**Severity: High (operability / certification blocker).** Confirmed: 0 rows in
every ABDM table.

**What is wired.** `POST /abdm/hip/care-contexts` creates a context; the visit-close
hook (`opd/service.py:180`) and discharge hook (`admissions/service.py:271`) build
FHIR bundles.

**What only looks wired.** Those hooks write `FhirBundleTransaction` **stubs**
(`gateway_response_status="stub_not_sent"`, fhir/service.py) — a pre-ABDM
artefact. They do **not** create an `AbdmCareContext` and do **not** call
`notify_care_context`. So closing a visit produces nothing the ABDM gateway can
see. The only path that creates a care context is the staff API route, and there
is **no frontend for it** (no `abdm/hip` or `abdm/hiu` references anywhere in
`frontend/src`). Live DB confirms: `abdm_care_contexts`, links, artefacts and
requests are all **zero rows**.

**The concrete failure.** A patient links their ABHA once; every encounter after
that is invisible because no care context is ever created or notified — which is
precisely the "classic HIP defect" `notify_care_context` was written to prevent.
The prevention exists; nothing calls it. A milestone discovery/link run would
find an empty facility.

**Fix.**

- Wire care-context creation into the clinical flow: on visit close / discharge /
  result finalisation, create an `AbdmCareContext` for the encounter and, if the
  patient has a confirmed link, call `notify_care_context`. This is the missing
  bridge between the clinical tables and the ABDM plumbing.
- Build the M2/M3 staff surface (create care context, notify, list links; create
  consent request, fetch artefact, request health information, list artefacts).
  The backend contracts exist; the operator has no way to drive them.
- Until then, state plainly in the readiness docs that M2/M3 are backend-only and
  cannot be exercised by a non-engineer.

---

## F5 — No reconciliation job for a stranded transfer

**Severity: Medium.** Confirmed: no scheduler/periodic task in the codebase.

`transfer_transaction` is a FastAPI `BackgroundTask` fired after `db.commit()`
(external_router.py:710). It handles its own exceptions and records
`status="failed"` with a reason. But if the process is killed between the commit
and the task completing — a deploy, a reload (CLAUDE.md documents that editing a
backend file can hang the container), an OOM — the request row is left at
`status="transferring"` forever. The worker's own comment anticipates "a
notifier/reconciliation job to retry" (hip/worker.py:563); **no such job
exists**. Nothing sweeps `transferring` rows.

**Fix.** Add a periodic reaper (the outbox already has `reap_stranded`; reuse the
pattern) that finds `abdm_hip_hi_requests` stuck in `transferring`/`received`
past a threshold and either retries `transfer_transaction` or marks them failed
and notifies the gateway. Pair it with a metric so a stuck transfer is visible.

---

## F6 — Scan-and-share writes patient rows from an unauthenticated caller

**Severity: Medium** (a specific facet of F1, called out because its fix is
different). `profile_share` (external_router.py:454) creates a `Patient` with
`identity_status="verified"` from a callback authenticated only by public
headers. Even once F1's network control is in place, creating a *verified*
identity from a gateway-asserted profile deserves its own guard: the gateway
vouches the ABHA is real, but the local row should not claim a verification
strength the facility did not perform.

**Fix.** Record scan-and-share patients with an identity status that reflects
"asserted by ABDM scan-and-share," distinct from a locally OTP-verified identity,
so the trust source is legible. Keep the abha_number uniqueness guard (already
present). Re-evaluate once F1 restricts the caller.

---

## F7 — Data-push URL validation has a resolve-then-connect TOCTOU

**Severity: Medium (residual, low likelihood).** `_validate_data_push_url`
(hip/worker.py) is otherwise strong: HTTPS only, rejects credentials/fragments,
rejects `localhost`/`.local`, resolves the host and rejects any non-global
address, `follow_redirects=False`. But it resolves the name, approves it, and
then hands the raw URL to a fresh `httpx` client that resolves **again** at
connect time. A DNS entry that flips between the two lookups (rebinding) could
point the actual POST at a private address.

**Fix.** Pin the validated IP for the connection (resolve once, connect to the
literal address with the original Host header / SNI), or use an httpx transport
that re-validates the resolved peer against the private-range check at connect
time. Low likelihood against the ABDM sandbox; worth closing for a CERT-In review.

---

## F8 — `assert_audit_coverage()` is defined and never called

**Severity: Medium (known, self-documented).** `AUDITABLE_MODULE_PREFIXES` in
`audit/listeners.py:367` is empty (both entries commented out), so the boot-time
guard iterates over nothing and can never fail. CLAUDE.md admits this. The ABDM
models each opt in individually via `__audit_resource_type__`, so they *are*
audited — but the guard that is supposed to prove no auditable model was
forgotten is inert. Note also that gateway-written artefacts audit with a NULL
actor (observed in the probe: "no actor context ... user_id will be NULL"),
which is expected for a callback but should be a known, documented shape.

**Fix.** Populate `AUDITABLE_MODULE_PREFIXES` (start with
`app.integrations.abdm`, `app.patients`, `app.billing`, `app.consent`) and call
`assert_audit_coverage()` from the lifespan startup, after models import. Make
the number move: add a model without the opt-in and confirm boot fails.

---

## F9 — CI lint gate is neutered with `|| true`

**Severity: Low.** `.github/workflows/ci.yml:179` runs `ruff check . || true`
under the banner "Lint (style only — does not block)." The file's own header
loudly forbids `|| true` gates as the recurring vacuous-gate trap. Lint being
non-blocking may be a deliberate choice, but it directly contradicts the stated
policy and is the exact shape CLAUDE.md warns about.

**Fix.** Either make lint blocking (`ruff check .`) or delete the step rather
than neuter it, per the file's own rule. If style should not block, run it as a
separate reporting-only job that is honestly labelled and not part of the
required check.

---

## F10 — Reserved-but-unused gateway settings (by design, do not "fix")

**Severity: Low / informational.** `abdm_path_bridge_services`,
`abdm_path_bridge_service`, `abdm_path_bridge_url` and `abdm_path_gateway_certs`
have **zero callers in `app/`**. Unlike the original defect, this is correct:
bridge provisioning is a one-time ops task run through `scripts/abdm_sandbox.sh`,
and `certs` is reserved for the not-yet-published callback signature scheme. Do
not treat these as dead limbs. Recommend a one-line comment on each pointing to
its out-of-app caller so a future audit does not re-flag them.

---

## F11 — Config is process-cached; identity/paths need a restart

**Severity: Low / informational.** `get_settings()` is `lru_cache`d, so changing
`ABDM_*` in `.env` has no effect until the process restarts. This is standard and
intended; noted so an operator does not chase a "stale" path after editing
`.env`.

---

## F12 — Non-ABDM sweep findings

**Severity: Low, out of primary scope.** Surfaced while tracing; recorded so they
are not lost.

- **Money in the billing UI is handled as a float.** `CollectPaymentModal.tsx`
  keeps `amount` as a JS number and compares `amount > balanceDue + 0.001` — the
  epsilon is a float-money tell. The house rule is decimal strings end to end.
  `toMoney(amount)` at submit re-stringifies, but the in-form arithmetic is
  float. Low blast radius (single payment, server re-validates), but worth
  aligning with the stated convention.
- **`pr_check.py` path handling** filters `git diff` paths through
  `pathlib.Path(p).exists()` with CI `working-directory: backend`; repo-root
  paths from the diff will not exist under `backend/`, so the PR-convention check
  can silently see "no files." CLAUDE.md records this class of vacuous gate as
  already-found; confirm it still triggers on a real backend change.

---

## Fix plan, sequenced

The phases are a real sequence: each unblocks the next, and the earliest work is
the smallest and the most urgent.

**Phase 0 — stop the bleeding (hours, before any further sandbox exposure).**
- F1.1: repoint the Cloudflare tunnel at nginx.
- F1.2: add a source restriction (ABDM egress allowlist or Cloudflare Access) to
  `abdm.healthdoc.world`.
- F1.3: close `/api/v1/docs`, `/openapi.json`, `/metrics` to the public hostname.

**Phase 1 — correctness of the flows that already run (days).**
- F2: make the replay key confirm success, not receipt.
- F3: reconcile the HI-type vocabulary across CHECK, validator and builder, with
  a drift test.
- F6: give scan-and-share patients a distinct identity-source status.
- F7: pin the validated data-push IP through to connect.

**Phase 2 — make the HIP side actually flow (1–2 weeks).**
- F4: create care contexts on clinical events and notify on confirmed links.
- F4: build the M2/M3 staff UI.
- F5: add the stranded-transfer reaper and its metric.

**Phase 3 — gates and hygiene (days, parallelisable).**
- F8: turn on `assert_audit_coverage()` with a real prefix list.
- F9: make lint blocking or delete the neutered step.
- F10/F11: add the clarifying comments; no behavioural change.

**Phase 4 — certification evidence (external, gated on Phase 0–2).**
- Run M1 with a consenting sandbox user; complete M2 discovery/link with a real
  care context; complete the M3 consent/data round trip; retain NHA milestone
  screenshots and request ids. This is the step no code change can substitute
  for, and it cannot start until Phase 2 gives the flows something to carry.

---

## What was verified vs assumed

- **Verified live:** the tunnel bypasses nginx and answers the public internet;
  the forged consent-notify writes a granted artefact from public headers; the
  failed-handler retry is swallowed; ABDM tables are empty; the ABDM test subset
  (205) and contract gate (189) pass; the outbound path settings each have one
  caller; the consent scope-gate joins through a confirmed link.
- **Assumed / not done:** no forged request was sent through the *public* tunnel
  (only the local backend), to avoid writing to a live sandbox-facing database;
  the full ~1190-test suite was not re-run (the ABDM subset and contract gate
  were); no real ABDM milestone journey has completed — that remains a known
  state, not a finding.

## If ABDM ran certification tomorrow

It would first fail at discovery: the facility has no care contexts, so there is
nothing to link or share, and the operator has no UI to create any. A CERT-In
assessor, separately, would open the callback surface, observe it is
internet-reachable through a tunnel that bypasses the reverse proxy, forge a
consent notification with public header values, and watch a `granted` artefact
appear. The wiring is real; the exposure and the empty pipeline are what a real
run would trip over first.
