# Explicit historical ABDM document registration

Updated: 9 September 2026. Engineering maintenance procedure, not milestone
certification or clinical approval.

## What this closes

New clinical completion already publishes document-scoped care contexts. Older
records may have no context at all. The replacement
`scripts/maintenance/backfill_care_contexts.py` creates only documents named in
an operator-reviewed manifest, using the same publisher as clinical completion.
The original whole-database scanner has been retired; it was not run.

- Preview by default. Maximum 100 unique documents and 128 KiB of JSON.
- Exact facility, active operator from that facility, and explicit patient IDs.
  Deleted, merged, foreign, draft, superseded and unverifiable records refuse.
- One finalized document per context, with its source-derived date and original
  clinical author. The operator is the context creator and audited actor, not a
  substitute clinician. A nonblank source-author registration is required;
  registration authenticity and clinical sign-off still need review.
- Apply is all-or-nothing, including contexts, notification jobs and audit rows.
  A PostgreSQL patient lock serializes overlapping runs.
- Repeating apply returns existing contexts and does not reset delivery jobs.
  Existing contexts with missing/changed dates are refused, not rewritten.
- No HTTP, new patient links, consent changes or patient-identity edits.
  **Creation queues notification work. A running worker can send it later.**

This is a privileged CLI: permission comes from controlled database/process
access, not from the manifest. An operator UUID is attribution, not proof of a
Keycloak role. Do not expose this command as an unauthenticated web endpoint.

## Before execution

1. Obtain approval for the exact target database, facility and selected records.
   Keep this separate from approval to deploy code or create a PR.
2. Use a rehearsed backup and schema at migration `0067`. Keep the delivery
   worker stopped and prevent other delivery processes from consuming new jobs.
3. Have the facility review source finalization, author registration and document
   content. Do not guess missing practitioner IDs or replace the source author.
4. Store the manifest outside Git with restricted permissions. It contains
   internal patient/document identifiers; output is also restricted operational
   evidence. Do not add names, Aadhaar, ABHA, clinical text, tokens or keys.

## Manifest

Replace every placeholder with a reviewed, existing UUID. This example is
intentionally not directly executable:

```json
{
  "facility_id": "<approved facility UUID>",
  "operator_id": "<active operator UUID from that facility>",
  "documents": [
    {
      "patient_id": "<existing patient UUID>",
      "reference": "prescription/<finalized prescription UUID>"
    }
  ]
}
```

Allowed reference prefixes:

| Prefix | Source UUID |
|---|---|
| `encounter` | Closed consultation |
| `prescription` | Prescription belonging to a closed encounter |
| `lab-result` | Current final/corrected lab result version |
| `radiology-report` | Current final/corrected report version |
| `discharge` | Discharge with recorded date and nonempty summary |
| `wellness` | Closed encounter with measurements at or before closure |

UUIDs must use canonical lowercase, hyphenated spelling. Do not use `visit/`
or include a whole visit's records implicitly. Repeating a reference, extra
fields, invented document dates and unbounded input are rejected.

## Preview, review, then apply

Run from the repository root, after replacing the explicit host path below.
These commands start only a one-off maintenance process, not the delivery worker:

```bash
docker compose --env-file .env -f infra/docker-compose.yml run --rm --no-deps \
  -e PYTHONPATH=/code \
  -v /absolute/private/approved-manifest.json:/input/manifest.json:ro \
  backend python /scripts/maintenance/backfill_care_contexts.py \
  --manifest /input/manifest.json
```

Review every returned `reference`, `status` and `document_at`. `eligible` means
registration checks passed, not that a complete NRCeS bundle has been validated
or the patient has linked/consented. A generic `refused` intentionally does not
reveal whether a record is foreign, absent, draft or has an invalid author.
Investigate with authorized source workflows; do not loosen the checks.

Only after approval, repeat with explicit apply and the matching facility:

```bash
docker compose --env-file .env -f infra/docker-compose.yml run --rm --no-deps \
  -e PYTHONPATH=/code \
  -v /absolute/private/approved-manifest.json:/input/manifest.json:ro \
  backend python /scripts/maintenance/backfill_care_contexts.py \
  --manifest /input/manifest.json --apply \
  --confirm-facility "<approved facility UUID>"
```

Apply revalidates the current source. A refusal rejects the entire batch, even
if other documents were eligible. Separate approved subsets into new manifests;
do not silently drop refusals.

| Exit | Meaning |
|---|---|
| 0 | Preview fully eligible/existing, or apply committed successfully |
| 2 | Invalid input/operator/confirmation, or one or more refused documents |
| 1 | Unexpected database/runtime failure; transaction outcome is not confirmed |

After a connection error around commit, preview before retrying: the database
may have committed even though the client did not receive confirmation. Replays
do not duplicate contexts or restart completed jobs. Do not manually delete
audit rows or notification state to force a retry.

## After registration

- Compare returned context IDs with the facility's document list and audit trail.
- Validate actual generated documents using the assigned NRCeS rules. This
  registration tool does not add missing PACS UIDs, correct clinical content,
  create immutable sign-off snapshots or validate external registry values.
- Review new queued jobs before any separately approved worker start. Each
  notification still needs the correct confirmed patient link. Registration is
  not consent and does not widen an existing link.
- Existing undated contexts use the separate admin reconciliation flow. This
  command does not recover missing jobs for existing contexts, rewrite adopted
  dates or repair legacy requests with unknown original consent scope.

See [verification and recovery](abdm-local-verification-and-recovery.md) for
worker controls and [current gaps](bahmni-abdm-m1-m2-m3-gap-analysis-2026-09-08.md)
for M1/M2/M3 requirements. No application-data backfill or live delivery was run
while implementing this tool.

## Verification recorded

- 45 targeted regressions passed, including all six reference kinds, explicit
  scope, author/operator separation, preview, refusals, replay and CLI errors.
- Three run against the migrated PostgreSQL test database: observed concurrent
  lock contention with exactly one context/job per document; rollback after a
  later write fails; and CLI rollback after a simulated commit failure.
- Full gate: **1,490 backend + 14 script tests passed**, four pre-existing
  Pydantic alias warnings; **74 migrations, linear head 0067**.
- Changed-file Ruff and explicit PR convention scan passed. The normal PR
  checker may say no Python files while work is uncommitted; that is not counted
  as validation of this follow-up.
- The first full run exposed the SQLite fixture's legacy savepoint behavior in
  the new commit-failure test. Its outer transaction is now explicit, and the
  same state-rollback requirement is tested on PostgreSQL. No production
  validation was relaxed. See [SQLAlchemy's transaction documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#legacy-transaction-mode-with-the-sqlite3-driver).
