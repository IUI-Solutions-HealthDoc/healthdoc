# PR review checklist — HealthDoc

**Run the machine first, then read what it can't judge.**

```bash
# on the PR branch
python backend/scripts/pr_check.py                      # convention blockers
python backend/scripts/spec_check.py                    # doc ↔ enums drift
python backend/scripts/check_migration_integrity.py     # chain, forks, downgrades
cd backend && pytest -q                                 # tests
```

CI runs all four. A **blocker** fails the build — do not review further until it's green.

---

## What the tools already check (don't spend review time here)

| Rule | Catches |
|---|---|
| `SEQ-RACE` | `MAX(col)+1` identifier allocation (duplicate UHID/token/receipt) |
| `TZ-DATE` | `CURRENT_DATE` / `now()::date` — the 00:00–05:30 IST wrong-day bug |
| `MONEY-FLOAT` | float/REAL on any amount column |
| `PII-AADHAAR` | Aadhaar on a log/plaintext path |
| `ENUM-WIDTH` | enum-backed column narrower than `varchar(50)` |
| `MIXIN` | hand-rolled `id`/`created_at`/`created_by` instead of `UUIDPk`/`Timestamps`/`Blame` |
| `MIG-DOWNGRADE` / `MIG-REVISION` / `MIG-0018` | missing or empty `downgrade()`, bad revision id, revived 0018 |
| `MONGO-DUALWRITE` | direct Mongo write in a request handler (silent note loss) |
| `MODULE-BOUNDARY` | a module querying another module's tables directly |
| `IDEMPOTENCY` | creating POST with no `Idempotency-Key` handling |
| `CONFIG` | `os.environ` outside `common/config.py` |

Use `# pr-check: ignore` on a line only with a written reason in the PR.

---

## What a human still has to judge

1. **Is the migration number right, and does it merge in chain order?** (schema §2)
2. **Does every new table match §3 exactly** — column names, nullability, FK targets, indexes on FK columns?
3. **Enum values**: added to `enums.py` *and* the doc, in the same PR?
4. **Deletion policy**: clinical/financial = never deleted; append-only tables have blocking triggers (§5, §6).
5. **Audit**: does every mutation write `audit_logs` in the same transaction?
6. **Consent**: does every clinical read pass the gate and log to `data_access_log`, including denials?
7. **Module toggles**: if this touches pharmacy/lab/radiology/OT/blood-bank, does the flow still work with it **off**? (§Module toggle behavior)
8. **Concurrency**: mutable clinical/financial rows carry `row_version`; PATCH honours `If-Match` (§4A.2).
9. **Tests**: does the PR add a test for the thing it claims to fix?
10. **Size**: ≤400 lines. Bigger needs a stated reason.

## Verdict template

```
Blockers: <from pr_check, or none>
Spec:     <migration number / §3 match / enum sync>
Safety:   <audit + consent + deletion policy>
Toggles:  <works with the optional module off? n/a>
Tests:    <present? meaningful?>
Decision: approve | request changes
```
