# ABDM local verification and recovery

Updated: 13 September 2026. Current follow-up: `fix/abdm-live-operations`.
This is an engineering runbook, **not evidence of NHA milestone approval**.
The status table in [the gap report](bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md)
distinguishes implementation from unproven deployment and clinical behaviour.

## 1. Before changing the running application

The approved local application upgrade **0060 → 0067** completed on 9 September
2026 (IST). A custom-format PostgreSQL backup restored into an explicitly named
disposable database. Row-count and SHA-256 comparisons over every original
column confirmed **121 tables / 10,912 existing rows unchanged** after restore,
after clone migration, and after application migration. Both new job/reply
tables were empty. The disposable clone was removed after verification.

Backup: ignored `backups/abdm-0060-20260909/healthdoc_healthdoc_20260908T194928Z.dump`,
created with `umask 077`. The filename uses UTC. Keep it restricted and outside
Git. The API was restarted; **the delivery worker was not started**. This was a
local application-copy rehearsal, not a production dump or complete disaster
recovery test, and it did not prove decryption after loss of the original keys.

For future deployments, obtain approval for the exact database and backup location.
This machine may be the origin for `abdm.healthdoc.world`; a local restart or
migration can affect the public sandbox. Worker start still needs queue and
external-delivery approval; migration approval does not imply that approval.

Before approving deployment:

1. Stop new sandbox clinical activity and ensure the background delivery worker
   is stopped. Inventory existing queued jobs without publishing their contents.
2. Use `backend/scripts/backup/backup_postgres.sh` for a restricted-permission
   logical PostgreSQL dump. Do not commit it. Verify the archive and restore it
   into an explicitly named **disposable database**, never onto the live database.
3. Rehearse 0060 → 0067 against that populated copy. Verify existing patient,
   consent/link and encrypted-key rows still read correctly. Empty-schema tests
   do not prove populated-data compatibility.
4. Back up and document the encryption-key versions, Redis configuration and
   relevant secrets through the approved secrets process. A PostgreSQL dump alone
   is not a complete Redis/Keycloak/MinIO/MongoDB/PITR recovery plan.
5. Apply migrations 0061–0067 to the approved target, then restart/rebuild the
   application. Do not blindly downgrade: scope metadata and received content
   are not disposable. Prefer the rehearsed restore procedure.

No real patient data, ABHA/Aadhaar numbers, OTPs, session credentials or private
keys belong in screenshots, command output, logs, git or test reports.

## 2. Worker and operator controls

The development worker is explicitly opt-in. **Starting it can send existing
queued requests to the configured ABDM gateway.** Inspect and approve the queue,
target sandbox, identities and ingress before starting it.

After approved migration and queue review, the command from the repository root is:

```bash
docker compose --env-file .env -f infra/docker-compose.yml \
  -f infra/docker-compose.abdm-worker.yml up -d abdm-worker
```

Stop only that worker with:

```bash
docker compose --env-file .env -f infra/docker-compose.yml \
  -f infra/docker-compose.abdm-worker.yml stop abdm-worker
```

This override is for development/sandbox use, not a reviewed production deployment.
It runs `python -m app.integrations.abdm.job_runner`; API background tasks are
latency optimizations and cannot replace the continuously running poller.

| Job state | Meaning | Correct action |
|---|---|---|
| `pending` | Ready later, retrying transport, or waiting for confirmed document linkage | Read the safe reason; resolve the prerequisite. |
| `leased` | A worker owns the attempt | Do not manually reset it. A heartbeat renews the lease. |
| `done` | The outbound job finished | This is not necessarily patient consent or gateway callback completion. Check the business record. |
| `dead` | Retry budget exhausted | Fix the cause, then use admin retry. Expired consent/keys need a new clinical request. |

Admin UI: `/admin/abdm-sync`, **ABDM delivery jobs** section. It lists only the
signed-in facility's jobs. Retry requires an `Idempotency-Key`; replaying that
same operation cannot reset a later delivery cycle. Do not bulk-reset statuses
or clear delivery timestamps with SQL.

Encrypted transfer pages are frozen before the first push. A recovery attempt
uses those same bytes and skips pages whose delivery was committed. An ambiguous
network failure can resend a page the receiver already accepted; the receiver
must accept the exact replay and reject changed content. This is at-least-once
delivery with deduplication, not a distributed exactly-once guarantee.

Migration 0067 commits HIP consent/data-request and HIU consent acknowledgement
intent with the accepted business state. The reply job schedules transfer/fetch
only after acknowledgement succeeds. Each fetch uses its durable job ID on the
wire; an incoming artefact must match that dispatched job, not merely a known
consent ID. Migration 0070 extends durable intent to successful mediated-link
confirmation: the exact OTP proof can retry a database rollback under its
original Redis TTL, and committed acknowledgement retries use a keyed proof
fingerprint without retaining the code. These jobs never enqueue clinical
transfer. Migration 0071 extends that durable boundary to discovery, link-init,
negative confirmation and Scan-and-Share acknowledgements. Their frozen reply
snapshots are encrypted with per-reply associated data, expire within ten
minutes, and are erased by cleanup after successful delivery or expiry. A
callback replay cannot extend that deadline or restore erased content.

Link-init commits before attempting SMS. Redis permits one delivery attempt
per link under its original deadline. Concurrent/repeated work cannot generate
another OTP, reset attempts or change the recipient. An ambiguous SMS outcome
requires an explicit new patient action, not automatic redelivery. Wrong-proof
retries with the same callback ID also cannot consume the attempt budget twice
after a database rollback. The configured worker is required to dispatch these
replies; receipt of HTTP 202 alone does not mean a reply was delivered.

The owner deferred SMS-provider setup, so this alternative remains disabled
operationally and is tested with synthetic data, not a live participant. Keep
the general outbound worker stopped until its entire queue is reviewed. For an
approved single operation, use the targeted job dispatcher rather than draining
unrelated jobs. Recovery
when the gateway accepted a fetch but never sends a usable callback still needs
an explicit callback-timeout/redelivery workflow.

## 3. Legacy document reconciliation

New clinical completion events create canonical document contexts in the same
database transaction. Old contexts with no `document_at` fail closed.

Admin-only `POST /api/v1/abdm/operations/contexts/reconcile` accepts:

```json
{"context_ids":["<explicit existing context UUID>"],"apply":false}
```

Supply an `Idempotency-Key`. Preview first; review every result. Use a **new key**
with `apply:true` only for approved rows. The response distinguishes `eligible`,
`reconciled`, `refused`, `unavailable` and `unchanged`.

This operation only fills missing dates on existing, unambiguous canonical source
references. It does not create missing historical contexts, invent source authors,
rewrite an adopted date, reinterpret `visit/...`, widen confirmed links, or repair
legacy transfer requests with unknown scope.

For **missing** contexts, a separate preview-first maintenance CLI is now built:
[explicit historical registration](abdm-historical-backfill.md). It accepts only
named patient/document pairs for one named facility and active operator, refuses
the whole batch if any source is unsafe, and atomically creates contexts, audit
records and notification jobs. It does not rewrite an existing context or start
delivery. The original all-facility script was archived and replaced, not run.
No application-data manifest has been applied. Execute only after facility
review, backup and approval, with the worker stopped.

## 4. Browser action-level verification

Use the approved local certificate and test accounts. Accept any certificate
warning manually. Run browser tests separately from the heavy backend gate.

### Doctor: document sharing and receiving

Open `/doctor/abdm` as `dev.doctor`:

1. Search a permitted synthetic patient by name and date of birth. Confirm a
   verified ABHA binding; no fabricated identifier or another person's identity.
2. Select finalized documents for HIP linking. Verify one operation per HI type,
   pending/confirmed/error status, callback correlation and expired-token recovery.
3. Request outside records with dates, supported HI types and access expiry.
   A queued job is not a grant. Capture the actual patient grant/denial externally.
4. Grant **less** than requested. Request data and verify the outbound request uses
   the artefact's narrower dates/types and real stored key material.
5. Receive encrypted data from the authorized external HIP. Verify page progress,
   source HIP, document date and read-only display. No automatic diagnosis or
   prescription import is implemented.
6. Revoke consent, including a partial transfer. New reads must refuse content,
   outstanding keys must clear, and the scheduled cleaner must clear stored
   ciphertext while preserving approved receipt metadata.
7. Test a second facility, another doctor and an unauthorized role. Content is
   restricted to the requesting clinician; shared clinical-team access has not
   been approved or implemented.
8. Retry exact/changed pages, expire the key, repeat callbacks, and test a worker
   restart. Record actual outcomes, not just an HTTP 202 or a screenshot of a table.

The record viewer rechecks permission periodically and when visibility changes;
the API checks on every read. A previously displayed page is not remote-erased
instantaneously. Clinical screenshots/downloaded copies need their own policy.

### Reception: M1

Existing flows request and verify Aadhaar enrolment OTP or existing-ABHA login OTP.
Verify owner/facility/patient rejection, wrong/expired OTP, duplicate ABHA and
network failure. Only an authorized participant may supply the real OTP privately
in the application.

Still to build: separate mobile-verification continuation, ABHA address selection/
creation, accurate account-token purpose/expiry, and real Scan-and-Share reception
queue tickets. Confirm whether profile/card functions are on the assigned checklist.
Do not present the present success screen as all of M1 being complete.

## 5. External and clinical requirements

- Assigned current NHA M1/M2/M3 checklist and expected FHIR/profile versions.
- Declared single-facility sandbox service mapping: gateway client, HIP, HIU,
  facility registration and actual practitioner registrations. Do not substitute
  placeholders. New HIU and reply workers explicitly refuse another facility's
  work rather than using the configured service identity for it.
- Approved callback ingress controls. UUIDs, timestamps and recipient headers
  are not cryptographic proof of gateway identity. Direct HIP→HIU traffic must
  remain compatible with authenticated encryption and transaction binding.
- Authorized participant and approved OTP-delivery relay for PHR-initiated linking.
- Clinical decisions on finalization/signatures and lab/discharge authorship.
- External interoperability: received records currently require a verified ABHA
  patient identifier. A HIP emitting only its local patient identifier will be
  refused until an explicit, reviewed binding strategy exists.
- Actual generated-and-received documents validated against the assigned NRCeS
  and terminology rules; current bounded structural/consent checks are not a
  substitute for that validator.
- Historical plaintext outbox handling, backup retention and restoration rules.
  New writes use protected storage; historical copies have not been erased.

## 6. Repeatable engineering gates

```bash
make test-pg
make contract
cd frontend
npm test
npm run typecheck
npm run build
```

Check the command's own exit code and test summary. `make test-pg` includes script
tests and migration integrity on a full run. Its default PR diff check may find no
files while work is uncommitted; pass explicit changed/new Python files to
`backend/scripts/pr_check.py` as a separate step. Do not count skipped PostgreSQL
tests, mocked gateway calls or sample bundles as live milestone evidence.
