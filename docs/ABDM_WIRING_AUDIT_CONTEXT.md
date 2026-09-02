# Context for a wiring audit — HealthDoc ABDM M1/M2/M3

Paste this whole file as the first message of a fresh session, then let the model
work. It is written to be handed to a model that has **never seen this repo**.
Its one job: decide whether the ABDM integration is *wired*, not whether the
tests are green. Those are different questions, and the gap between them is
exactly what has bitten this project before.

---

## 0. Your mission, stated once

Verify that ABDM Milestones **M1 (ABHA identity), M2 (HIP), M3 (HIU)** are wired
end to end: that every outbound call has a caller, every inbound route is mounted
and reachable, every path setting is actually used, and every milestone flow
connects from the staff action to the gateway and back. Report what is genuinely
wired, what only looks wired, and what is missing — ranked by how badly a real
ABDM certification run would trip over it.

**Do not trust a green suite.** The defining bug of this integration was ten
gateway path settings that were referenced *nowhere outside the config file* —
the package could receive and could not speak — and the full suite passed the
entire time, because no test fails when a function is simply never called. Your
value is in checking the wiring the tests do not.

Read `CLAUDE.md` at the repo root first. It is the project's own hard-won list of
traps and conventions; treat it as ground truth about *why* things are shaped the
way they are.

---

## 1. What the project is

HealthDoc HMIS — a hospital system for Indian facilities. FastAPI + PostgreSQL
backend, Next.js 16 + Keycloak frontend, all behind nginx in Docker Compose.
Targeting ABDM certification and a CERT-In WASA audit.

ABDM (Ayushman Bharat Digital Mission) is India's health-data exchange. A
facility acts as a **HIP** (Health Information Provider — it holds records and
shares them) and an **HIU** (Health Information User — it requests records from
elsewhere). Both talk to a central **gateway/consent-manager**. The exchange is
asynchronous throughout: you POST a request, get an acknowledgement, and the real
answer arrives minutes-to-days later on a **callback** the gateway makes to you.

- **M1** = ABHA identity: verifying a patient's health id.
- **M2** = HIP: linking care contexts to an ABHA, answering discovery, honouring
  consent, transferring an encrypted FHIR bundle when asked.
- **M3** = HIU: requesting consent, requesting health information, decrypting the
  bundle that a HIP pushes back.

## 2. How to run it and prove the ground truth

```bash
cd ~/Desktop/healthdoc
make up                              # stack should already be running; this is idempotent
make test-pg                         # THE GATE — host venv, real Postgres. Expect ~1190 passing.
make contract                        # every frontend API call exists in OpenAPI. Expect ~189.
make audit-deps                      # pip-audit + npm audit, must be zero both ecosystems
```

`make test-pg` is the gate CI approximates; `make test` runs in-container and
**skips DB tests**, so a green `make test` is not the same claim. The sandbox is
live: the stack reaches ABDM through a Cloudflare named tunnel at
`https://abdm.healthdoc.world`, and the app is served locally at
`https://localhost` (self-signed) and over the LAN.

**Do not commit ABDM credentials and do not add them to CI.** The client tests
are fully mocked and must stay that way. `.env` holds live sandbox values and is
gitignored — read it to understand config, never echo its secret values into a
report or a commit.

## 3. Where everything lives (the map)

```
backend/app/integrations/abdm/
  client.py            The ONLY thing allowed to call the gateway. Session token
                       cache, REQUEST-ID/TIMESTAMP/X-CM-ID headers, typed errors
                       (AbdmNotConfigured / Unavailable / AuthError / Rejected).
  callback_auth.py     Inbound authentication. TWO schemes live here — see §5.
  contracts_v3.py      Pydantic models for the v3 wire shapes.
  external_router.py   The inbound v3 callback routes (mounted in app/main.py).
  fhir/builder.py      Builds the FHIR bundle a HIP transfers, per HI type.
  identity/            M1. ABHA verification. router.py holds _VERIFY_PATH.
  hip/
    gateway.py         M2 OUTBOUND wire calls (the half that was missing).
    router.py          M2 staff routes + the /api/v1/... legacy callbacks.
    service.py         M2 state + policy (authorise_hi_request, care-context scope).
    worker.py          The transfer worker: builds + encrypts + pushes a bundle.
    link_otp.py        HIP-initiated link token / OTP flow.
    models.py          8 tables across hip/ and hiu/.
  hiu/
    gateway.py         M3 OUTBOUND wire calls.
    router.py          M3 staff routes + legacy callbacks.
    service.py         M3 state + the ECDH key lifecycle.
    models.py
  hi_crypto.py         ECDH X25519 + HKDF + AES-256-GCM. The transfer crypto.

backend/app/common/config.py   All abdm_* settings, INCLUDING the path settings.
backend/tests/integrations/    21 abdm test files; test_abdm_gateway_calls.py and
                               test_abdm_gateway_paths.py are the wiring ones.
```

Config authority: **every gateway path is a Settings field**, not a constant.
This is deliberate — a wrong path is then an env change, not a release. The
milestone → path mapping is `abdm_path_hip_*`, `abdm_path_hiu_*`,
`abdm_path_bridge_*` in `config.py`.

## 4. Known-good — verified, do not re-litigate

These were confirmed against the live sandbox on 2026-09-01/02. Spend your time
elsewhere unless you find contradicting evidence:

- The gateway session works. `POST /api/hiecm/gateway/v3/sessions` → 200 with a
  valid access token.
- The bridge is provisioned: URL `https://abdm.healthdoc.world`, two services
  registered and active — `SBXID_053401_HIP` and `SBXID_053401_HIU`.
- The v3 gateway paths exist. Each was probed by GET → 404 means "no such route",
  anything else (405/400/200) means the route is there. All corrected paths pass;
  the ten old `/api/hiecm/v3/...` single-base paths all returned 404. This is an
  *existence* proof, not a payload proof.
- M1 verification is live: `_VERIFY_PATH = /v3/profile/login/search`, on the ABHA
  host (not the gateway), body key `ABHANumber` (capitalised), value hyphenated.
- `facilities.hfr_facility_id` must equal `ABDM_HIP_ID` or inbound HIP callbacks
  404 at `_facility_for_hfr_id`. DEV001 is set to the HIP service id.

## 5. What to scrutinise — the actual audit

Work through these. For each, the failure is *silent* unless you look.

1. **Every gateway path setting has a caller.** The original bug. Grep each
   `abdm_path_*` setting and confirm it is referenced in `gateway.py`,
   `external_router.py`, `worker.py` or a router — not only in `config.py` and a
   test. A setting used nowhere is a dead limb.

2. **Every route in `external_router.py` is mounted AND reachable.** It is
   included in `app/main.py`. Prove it end to end by POSTing to a few paths
   through the running app and confirming you get validation/auth codes
   (400/401/422/503), not 404. A 404 means the route the gateway will call does
   not exist for it.

3. **Inbound callback authentication — the load-bearing question.** Read
   `callback_auth.py` carefully. There are two schemes:
   - the *legacy* `/api/v1/...` callbacks use a shared secret and are
     fail-closed (503 when `ABDM_CALLBACK_SHARED_SECRET` is unset);
   - the *v3* `/api/v3/...` callbacks (the ones ABDM will actually call) verify
     `X-CM-ID`, `X-HIP-ID`/`X-HIU-ID`, timestamp freshness and replay — **all of
     which are public values.** The file's own docstring says so, and says
     "source restrictions belong at the public edge until NHA publishes [a
     signature] scheme."
   Now verify the claim that "the edge protects it." The stack reaches ABDM
   through the Cloudflare tunnel `abdm.healthdoc.world`, which points **straight
   at the backend and bypasses nginx** (see `~/.cloudflared/config.yml` and the
   note in `infra/nginx/`). So ask: is there ANY source restriction on that path?
   If not, a v3 consent/data callback is forgeable by anyone who knows the public
   HIP id and `sbx`. Test it: craft a schema-valid `hip_consent_notify` callback
   with only public headers and see how far it gets — record whether a forged
   consent artefact is written or only rolled back incidentally. This is the
   single most dangerous surface in the integration; grade it honestly rather
   than assuming the edge covers it.

4. **The M2 transfer actually completes.** Trace `transfer_transaction` in
   `hip/worker.py`: it is fired as a FastAPI `BackgroundTask` from
   `external_router.py` after `db.commit()`. Confirm the chain builds a FHIR
   bundle (`fhir/builder.py`), encrypts it per-bundle (`hi_crypto` /
   `encrypt_bundle_for_hiu`), pushes to the HIU's `dataPushUrl`, and calls
   `notify_hi_transfer`. A BackgroundTask that raises disappears silently — check
   what happens to the request row on failure, and whether a dropped transfer is
   observable.

5. **The FHIR bundle is real per HI type.** `fhir/builder.py` maps clinical data
   to Prescription / DiagnosticReport / OPConsultation / DischargeSummary etc.
   Check that each declared `hi_type` a care context can carry actually produces
   a populated bundle, not an empty shell. An empty-but-valid bundle is the
   frontend-shell failure mode this project has hit repeatedly.

6. **Consent is enforced by scope, not fetch-then-check.** A HIP must only
   release records the patient consented to AND that belong to a **confirmed**
   link. Read `service.list_care_contexts_for_transfer` and
   `authorise_hi_request`. Confirm release joins through a confirmed link, not
   the artefact alone — releasing on the artefact id alone hands another
   patient's contexts to anyone holding a valid artefact id.

7. **HIU asks within the artefact, not the request.** `request_health_information`
   must take its date range from the granted **artefact** (the manager may grant
   less than asked), never the original request. Confirm, and confirm the
   nullable-artefact-range guard refuses rather than substitutes.

8. **The house conventions still hold on the new code.** 404-never-403 for
   another facility's record; money/quantities as decimal strings on the wire;
   `Idempotency-Key` on mutations; facility scope from `CurrentDbUser` never the
   body; timestamps sent to ABDM as literal-`Z` UTC (isoformat's `+00:00` is
   accepted by some ABDM endpoints and rejected by others). Spot-check the new
   ABDM routes for each.

9. **Gates are not vacuous.** For any check whose output is a number
   (`make contract`, the path tests), make something change that number and
   confirm it moves. CLAUDE.md documents three gates that once passed while
   checking nothing.

## 6. Explicitly out of scope — do NOT file these as bugs

- No real ABDM *data exchange* has completed end to end against the sandbox —
  only session/bridge/path existence and M1 verification. "Never exchanged a real
  bundle" is a known state, not a defect to discover.
- NHCX and `integrations/abdm/consent/`, `nhcx/` being empty is by design; NHCX
  is out of this audit's scope.
- The callback shared secret being a placeholder on the *legacy* v1 routes is
  intentional fail-closed behaviour, not an unfinished feature.
- ABDM credentials absent from CI and client tests being mocked is a hard rule,
  not a coverage gap.

## 7. How to report

Rank findings by blast radius, most-severe first. For each: the file and line,
what is wired vs. what only appears wired, the concrete failure (inputs → wrong
outcome), and the smallest fix. Separate **"broken/forgeable now"** from
**"missing"** from **"works but risky."** If the whole thing is genuinely wired,
say so plainly and name the two or three things you would still not certify on.
End with one paragraph: *if ABDM ran their certification suite against this
tomorrow, where does it first fail, and what would we see?*
