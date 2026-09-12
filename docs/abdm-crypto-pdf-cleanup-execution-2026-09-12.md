# ABDM execution: crypto, PDFs, cleanup and live prerequisites

Date: 12 September 2026. Branch: `fix/abdm-otp-live-verification`.
Changes remain local/uncommitted alongside pre-existing work. No PR, push,
merge, NHA declaration or participant transmission was performed in this work.

## Agreed order and actual completion

| Step | Result | Remaining acceptance |
|---|---|---|
| 1. Independent crypto interoperability | Implemented; exact known-answer and fresh independent CLI exchanges pass | Real external sandbox exchange; production capacity/security assessment |
| 2. Safe PDF-containing records | Implemented; consent-bound backend tests and actual browser preview pass | Real external-HIP document, production-mode browser/CSP run, broader attachment formats if required |
| 3. Independent retention cleanup | Implemented; local one-shot succeeds, dedicated container running | Repeated scheduled-pass log proof and production deployment/alerting |
| 4. Pending link diagnostics | Same-secret registry and callback route reachability verified; link still pending | Exact original acceptance/callback trace or an explicitly justified quota-safe recovery |
| 5. One approved live M2/M3 round trip | Not executed | Renewed local consent, valid requester, participant PHR actions and successful linking |
| 6. Remaining assigned cases | Not complete | Case-by-case live evidence; Scan & Share tickets, OTP/SMS delivery, additional HI-type scope and implementations |

## 1. Crypto implementation

The previous implementation used RFC7748 X25519 and rejected Fidelius's
65-byte full EC point. Its invented 33-byte-prefix test established only a
self-consistent local convention. It did not prove reference compatibility.

`backend/crypto/HealthDocEcdh.java` delegates generation, key parsing, curve
checks and ECDH to Bouncy Castle 1.86. Python retains HKDF-SHA256 and AES-GCM.
No handwritten EC arithmetic, arbitrary DER stripping or key padding was added.
Private scalars and shared secrets use bounded local process pipes, not argv,
files, logs or an HTTP crypto service. Clinical plaintext never enters Java.

Docker installs/builds the runtime outside the dev bind mount. CI installs
JDK 21 and builds it before tests. Host setup: `make abdm-crypto` with JDK 17+
available; see [runtime setup](../backend/crypto/README.md).

Stored private keys now carry an encrypted `bc-curve25519-v1:` format marker.
Old unversioned keys are refused, not silently reinterpreted. Do not re-label
already frozen ciphertext or silently replay an old transfer. The local
preflight found **zero** stored transfer keys or received documents, so no
application-data migration was needed here.

Proof:

- Published Fidelius known-answer ciphertext matches exactly, including both
  raw-point and X.509 peer formats.
- A separate run of the actual Fidelius CLI at revision
  `4d9b4a5f65d61607dafcea3e28e3d257e425fcd9` and HealthDoc exchanged fresh
  synthetic plaintext successfully in both directions.
- Invalid points, P-256 keys, zero/out-of-range scalars and legacy storage
  formats are rejected. Tampering/private-key isolation tests remain active.
- Production dependency is checksum-pinned BC 1.86. The reference CLI's older
  libraries remain temporary test material and are not deployed. OSV returned
  no known advisories for BC 1.86; `make audit-deps` now includes this dependency.

Sources: [Fidelius](https://github.com/mgrmtech/fidelius-cli),
[NHA reference encryption](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v1/hip/hrp/dataTransfer/encryption/EncryptionService.java).
Reference agreement is not proof of NHA certification.

## 2. PDF intake and frontend

Valid NRCeS PrescriptionRecord compositions can reference Binary PDF content.
The receiver previously rejected every Binary. It now accepts bounded embedded
PDFs through Binary or inline attachments, including DocumentReference content.

Preserved/enforced boundaries:

- Final document/consented care context, HI type, clinical timestamp, facility,
  requesting clinician and verified ABHA patient checks still apply.
- The attachment must be reachable from the Composition through local bundle
  references. A disconnected Binary cannot smuggle a separate document in.
- PDF content type, base64, magic bytes, one-MiB attachment bound and optional
  FHIR size/hash checks. The existing two-MiB whole-document bound remains.
- Content stays encrypted at rest and unavailable after revocation/expiry.
  Binary security context must resolve to the same patient or patient-bound
  resource. No external attachment URL is fetched.
- PDF.js 6.3.289 renders only a canvas: no scripting manager, XFA forms,
  interactive annotations, PDF links, iframe, object, embed or download control.
  Size, page-count, pixel and rendering-time bounds limit resource use. Invalid
  or unsupported PDF content displays a visible failure, not an empty success.
- Source narrative remains escaped text. Raw base64 is omitted from the text
  viewer. Record switches remount the view; failed/hidden access refresh clears
  content and tears down the PDF worker/canvas.

The actual local-browser test logs in through Keycloak, intercepts only the
synthetic clinical responses, and exercises the real compiled viewer. Its PDF
contains a script and an external link; neither runs. It then refuses the
record refresh and verifies the canvas disappears and an error is displayed.
No real patient, consent or received record is created by this test.

Evidence (ignored/regenerable):
[manifest](evidence/abdm-pdf-ui/result.json),
[render](evidence/abdm-pdf-ui/check-1.png),
[refusal](evidence/abdm-pdf-ui/check-2.png).
Re-run with `cd frontend && npm run test:abdm-pdf-ui` against localhost.
Do not label this simulated transport as a milestone case passed live.

Remaining boundaries: remote-only attachment retrieval is intentionally absent;
encrypted/malformed/over-limit PDFs fail preview; visual canvas is not a full
accessible PDF text viewer. Production build passes, but production-mode
browser/CSP acceptance was not run. Full-page screenshot stitching places
fixed navigation at the current scroll position; this is not a separate UI
layout validation.

## 3. Independent cleanup

`python -m app.integrations.abdm.job_runner --mode cleanup --once` runs only
cleanup and returns nonzero on failure. Without `--once`, cleanup runs every
60 seconds, independent of the delivery consumer. Tests prove neither branch
calls `run_once()` or `_poll_jobs()`.

Local command executed successfully: **cleared items=0**. Dedicated
`abdm-cleanup` service from `infra/docker-compose.abdm-cleanup.yml` was started
and observed running. The general ABDM worker was not started. The preceding
read-only count found no received-content rows, transfer keys or link tokens;
therefore nothing material was erased. Original clinical records and backups
are outside this consent-cache cleanup.

Periodic log inspection was blocked by the tool approval usage limit; do not
claim repeated scheduler execution or alerting proof yet. Recheck once access
is restored:

```sh
docker compose --env-file .env -f infra/docker-compose.yml \
  -f infra/docker-compose.abdm-cleanup.yml logs --since 5m abdm-cleanup
```

Do not use `--remove-orphans` on the base compose file: it would remove this
intentionally separate service. Production deployment, monitoring, backups and
broader retention/legal policy remain separate work.

## 4. Live preflight and unresolved linking

At **08:38:54 UTC / 14:08:54 IST** the read-only metadata check showed:

- selected link pending, token absent, no confirmation;
- original request ID `d613360a-99e5-5fc4-873c-b804d01dba8a` retained;
- local participant consent no longer valid;
- dev requester registration number/type/registry fields not configured;
- 18 unrelated context notifications pending, one link-context job pending,
  two token jobs done; no outbound worker started;
- no received-content rows or stored transfer/link keys.

Read-only sandbox registry check using the configured credentials returned
HTTP 200, active/non-blocklisted bridge, correct callback URL, and active HIP
and HIU services. Public token callback **GET 405** shows a POST route exists;
it does not show that a real callback was authenticated, correlated or accepted.
`GET /api/v1/health` is 200 locally and 404 publicly because the existing tunnel
intentionally exposes only `/api/v3/*`. No ingress rule was relaxed.

The requested next empty-probe sweep and scheduler-log read were rejected
before execution by the approval service's usage limit. Do not bypass this
through an indirect tool. No new token-generation request or clinical payload
was sent; the missing historical acceptance status cannot be reconstructed
from `job.status=done`.

## 5–6. Inputs and work still required

1. Participant renews local consent, for the intended synthetic document only.
   Do not backdate, auto-renew or expand scope. PHR sharing approval is separate.
2. Facility administrator configures the genuine/NHA-approved clinician
   requester identity. No example registration number or invented attribution.
3. Finish original callback trace diagnosis, then decide a supported recovery
   within quota. Do not reset/replay jobs or start the general consumer blindly.
4. Follow the live sequences in the [runbook](abdm-m2-m3-next-day-runbook-2026-09-12.md),
   with the participant entering OTPs and approving/revoking in their PHR app.
5. Complete the [assigned case ledger](abdm-milestone-case-ledger-2026-09-10.md).
   Real Scan & Share tickets/expiry, OTP relay/SMS delivery, additional HI types,
   production callback-origin controls and external counterparty cases remain.

## Gates run

- Full `make test-pg`: **1,816 passed**, six existing Pydantic alias warnings;
  **14 script tests passed**; 76 migrations linear, head 0069. This is +22
  backend regressions over the previous 1,794, not a milestone percentage.
- Targeted PDF/received-record/key-lifecycle/cleanup set: **71 passed**.
- Crypto self-consistency **11 passed**; independent-vector/boundary **9 passed**;
  separate real Fidelius CLI cross-process test passed.
- Frontend **108 tests passed**, TypeScript and changed-view ESLint passed;
  production build passed; real local browser synthetic acceptance passed.
- npm installation audit zero vulnerabilities; BC 1.86 OSV query empty.
  This does not constitute a complete Java/container security assessment.
- Existing default PR checker selected no Python files. Do not treat that as
  changed-code verification; explicit touched-file Ruff/checker runs are used.
- Final centralized-runtime-setting/cleanup recheck: **24 tests pass**.
  Explicit application/config/status-script PR check: **zero blockers and zero
  warnings**; touched-file Ruff and `git diff --check` pass. Standalone build
  and reference-test tools read their JDK executable from the environment by
  design; the application reads it through central Settings.

Neither M1 nor M2/M3 certification has been declared complete.
