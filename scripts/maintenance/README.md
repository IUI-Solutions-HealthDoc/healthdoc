# One-off maintenance scripts

Scripts written to apply a specific mechanical change across the repo. **All four
below have already been applied and merged** — they are kept because each one
records exactly what was changed and why, in a form that can be re-read or
re-run to verify.

Every one is idempotent: running it a second time reports "already applied" and
changes nothing. That is deliberate, so re-running to check is safe.

Run them from the repo root.

| Script | Applied in | What it did |
|---|---|---|
| `fix_359.py` | #359 | Added the `order_number_counters` §3 definition block, relabelled the four DPDP tables 0021 → 0022a, moved `guardian_verification` to 0038, and added the missing §2 map rows for #353's 0035/0036/0037. |
| `fix_seed_facility_id.py` | #351, #352 | Added `facility_id` to the raw-SQL test seeds that predate 0021 and 0022. Two phases (`encounters`, `orders`) because `orders.facility_id` does not exist until 0022. Four encounters sites, three orders sites. |
| `fix_queue_counter_race.py` | #352 | Rewrote `_allocate_token_number` as an upsert. The original did `SELECT ... FOR UPDATE` and, on `IntegrityError`, called `db.rollback()` — which ends the *caller's* transaction, not just the failed INSERT. |
| `fix_notification_facility.py` | #366 | Added migration 0039 (`notification_history.facility_id`), updated the model and both writers, and added the §3 blocks for `doctor_reviews` and 0039. |

## Two lessons worth keeping

**`docs/database-schema.md` §2 is machine-read.** The "Builds" column is parsed
as a comma-separated table list unless the entry starts with `ALTER`. A row
reading `rename patients constraints to NAMING_CONVENTION` made `spec_check.py`
go looking for tables named `rename` and `constraints`. Start non-table entries
with `ALTER`.

**Grepping source for SQL misses split string literals.** `"INSERT INTO x "`
`"(a, b)"` and triple-quoted blocks both slip past a naive pattern — this cost
two rounds on the seed fix. The scan that found everything collapses adjacent
string literals and whitespace first:

```python
flat = re.sub(r'["\']\s*\n\s*["\']', '', src)
flat = re.sub(r'\s+', ' ', flat)
```
