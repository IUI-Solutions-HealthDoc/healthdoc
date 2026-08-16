#!/usr/bin/env python3
"""Renumber #383's migrations onto staging's head, and document them.

Run from the repo root on feat/243-integration-tests-core-journeys, AFTER
merging staging (which is a clean merge — the branches touch no common files).
Idempotent.

WHY
---
#383's four migrations were written when staging's head was 0034, so they
chain 0035 -> 0035a -> 0035b -> 0035c. Staging is now at 0040 and its own
0035 is patients_row_version, so the first one collides outright and the rest
hang off a revision that means something different.

Nothing about the migration bodies is wrong — only the numbers. They move to
0041 / 0041a / 0041b / 0041c, keeping the letter-suffix grouping that shows
they belong to one piece of work.

guardian_verification held 0041 in §2 and is still unwritten, so it moves to
0042. Ready work takes the number — the same rule applied to 0038, 0039 and
0040 already.

WHAT THEY FIX
-------------
All five gaps were found by writing the journey tests, not by inspection:
  0041   visit_number_counters — the table app/opd/visit_number.py has always
         needed for every POST /visits, and which no migration ever created;
         plus idempotency_keys.updated_at
  0041a  visits.row_version
  0041b  idempotency_keys.response_body -> jsonb
  0041c  lab_order_items status CHECK gains 'released'
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
VERSIONS = ROOT / "backend/migrations/versions"
if not VERSIONS.is_dir():
    sys.exit("run me from the repo root")

# (old file stem, new file stem, old rev, new rev, old down, new down)
MOVES = [
    ("0035_visit_number_counters_and_idempotency_fix",
     "0041_visit_number_counters_and_idempotency_fix", "0035", "0041", "0034", "0040"),
    ("0035a_visits_row_version",
     "0041a_visits_row_version", "0035a", "0041a", "0035", "0041"),
    ("0035b_idempotency_keys_response_body_jsonb",
     "0041b_idempotency_keys_response_body_jsonb", "0035b", "0041b", "0035a", "0041a"),
    ("0035c_lab_order_items_released_status",
     "0041c_lab_order_items_released_status", "0035c", "0041c", "0035b", "0041b"),
]

for old_stem, new_stem, old_rev, new_rev, old_down, new_down in MOVES:
    old_p = VERSIONS / f"{old_stem}.py"
    new_p = VERSIONS / f"{new_stem}.py"
    if new_p.exists() and not old_p.exists():
        print(f"~ {new_stem} already renumbered")
        continue
    if not old_p.exists():
        print(f"! {old_stem}.py not found — skipping")
        continue

    t = old_p.read_text()
    t = re.sub(rf'^revision = "{old_rev}"$', f'revision = "{new_rev}"', t, flags=re.M)
    t = re.sub(rf'^down_revision = "{old_down}"$', f'down_revision = "{new_down}"', t, flags=re.M)
    # docstring header lines
    t = t.replace(f"Revision ID: {old_rev}\n", f"Revision ID: {new_rev}\n", 1)
    t = t.replace(f"Revises: {old_down}\n", f"Revises: {new_down}\n", 1)
    t = t.replace(f'"""{old_stem}', f'"""{new_stem}', 1)

    new_p.write_text(t)
    old_p.unlink()
    print(f"+ {old_stem} -> {new_stem}  ({new_rev} <- {new_down})")

# stray pytest output committed to the repo
stray = ROOT / "backend/test_output.txt"
if stray.exists():
    stray.unlink()
    print("+ removed backend/test_output.txt")

gi = ROOT / ".gitignore"
if gi.exists() and "test_output.txt" not in gi.read_text():
    gi.write_text(gi.read_text().rstrip("\n") + "\ntest_output.txt\n")
    print("+ gitignored test_output.txt")

# ------------------------------------------------------------------ §2 map
DOC = ROOT / "docs/database-schema.md"
if DOC.exists():
    d = DOC.read_text()
    if "| 0041 | visit_number_counters" not in d:
        old_guardian = re.search(r"^\| 0041 \| guardian_verification \|.*$", d, re.M)
        rows = (
            "| 0041 | visit_number_counters_and_idempotency_fix | visit_number_counters "
            "(+ idempotency_keys.updated_at) | B5 (#383) — the table app/opd/visit_number.py "
            "has always needed and no migration created |\n"
            "| 0041a | visits_row_version | ALTER visits: row_version | B5 (#383) |\n"
            "| 0041b | idempotency_keys_response_body_jsonb | ALTER idempotency_keys: "
            "response_body -> jsonb | B5 (#383) |\n"
            "| 0041c | lab_order_items_released_status | ALTER lab_order_items: status CHECK "
            "gains 'released' | B5 (#383) |\n"
            "| 0042 | guardian_verification | ALTER patients: is_minor, guardian_verified, "
            "guardian_verification_method | B2 (W3) — moved again as written work took the "
            "number; still unwritten |"
        )
        if old_guardian:
            d = d.replace(old_guardian.group(0), rows, 1)
            print("+ §2: four rows added, guardian_verification -> 0042")
        else:
            print("! could not find the 0041 guardian row — add §2 rows by hand")

    if "**visit_number_counters**" not in d:
        anchor = "**prescriptions** `[Blame]`"
        block = """**visit_number_counters** (0041, B3/B5) — per-facility, per-day visit number allocator
```
facility_id UUID NOT NULL → facilities · counter_date date NOT NULL
seq int NOT NULL DEFAULT 0
UNIQUE (facility_id, counter_date)
```
Same shape as `order_number_counters` and for the same reason: `counter_date` is the
**business date** in the facility's timezone, never UTC, and allocation is a single
`INSERT ... ON CONFLICT DO UPDATE ... RETURNING` so the first visit of each day cannot
race.

The model in `app/opd/models.py` carried a TODO saying this table had no home in §2 since
it was written, and `app/opd/visit_number.py` has depended on it for every `POST /visits`
throughout. It was only surfaced by #383's OPD journey test, because unit tests build
schema from `Base.metadata` — which creates the table the migrations never did.

"""
        if anchor in d:
            d = d.replace(anchor, block + anchor, 1)
            print("+ §3: visit_number_counters block")
        else:
            print("! could not place the §3 block — add it by hand")

    DOC.write_text(d)

print("\nnow run:  cd backend && python3 scripts/check_migration_integrity.py .. "
      "&& python3 scripts/spec_check.py ..")
