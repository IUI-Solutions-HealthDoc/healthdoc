#!/usr/bin/env python3
"""Un-double-prefix ORM CheckConstraint names. Run from the repo root. Idempotent.

THE BUG
-------
common/db.py sets NAMING_CONVENTION["ck"] = "ck_%(table_name)s_%(constraint_name)s".
%(constraint_name)s interpolates *the name you pass*. So:

    CheckConstraint(..., name="status")                 -> ck_ot_schedules_status   OK
    CheckConstraint(..., name="ck_ot_schedules_status") -> ck_ot_schedules_ck_ot_schedules_status

Alembic's op.create_table does NOT apply the ORM convention, so migrations that
pass the full name produce the correct constraint in the database. The ORM then
renders a different name for the same constraint, and the two drift.

This only affects "ck". The "uq"/"fk"/"ix" templates are built from column names
and never interpolate the passed name, so an explicit uq_/fk_ name is used
verbatim and is harmless — which is why a naive grep for name="ck_|uq_|fk_"
reports dozens of false positives.

WHY THIS WAS MISSED
-------------------
A single-line grep for `CheckConstraint(... name="ck_` finds ZERO of these,
because every one is written across multiple lines. Collapsing whitespace first
finds all four. That is the third time this week the same blind spot has changed
an answer, and it is why pr_check.py should learn the rule.

NOT TO BE CONFUSED WITH 0037
----------------------------
0037 tried to rename nine *patients* constraints and failed, because those were
never wrong: the ORM passes the bare form there and 0006 created the prefixed
form, which is exactly the correct pairing. This script fixes the opposite
mistake, in different files.
"""
import pathlib
import re
import sys

# (path, table, full name in the DB, bare name the ORM should pass)
TARGETS = [
    ("backend/app/ot/models.py", "ot_schedules", "ck_ot_schedules_status", "status"),
    ("backend/app/ot/models.py", "ot_schedules", "ck_ot_schedules_time_order", "time_order"),
    ("backend/app/ot/models.py", "ot_records", "ck_ot_records_time_order", "time_order"),
    ("backend/app/integrations/abdm/fhir/models.py", "fhir_bundle_transactions",
     "ck_fhir_bundle_transactions_direction", "direction"),
]

if not pathlib.Path("backend/app").is_dir():
    sys.exit("run me from the repo root")

fixed = skipped = absent = 0
for rel, table, full, bare in TARGETS:
    p = pathlib.Path(rel)
    if not p.exists():
        print(f"~ {rel} not on this branch — skipping {full}")
        absent += 1
        continue

    text = p.read_text()
    needle = f'name="{full}"'
    if needle not in text:
        print(f"~ {full}: already bare (or renamed)")
        skipped += 1
        continue

    text = text.replace(needle, f'name="{bare}"', 1)
    p.write_text(text)
    print(f"+ {rel}: name=\"{full}\" -> name=\"{bare}\"  (renders {full})")
    fixed += 1

print(f"\n{fixed} fixed, {skipped} already correct, {absent} not on this branch")

# Re-scan multiline-safe so the script proves its own work.
print("\nremaining double-prefixed CheckConstraints:")
found = 0
for p in pathlib.Path("backend/app").rglob("models.py"):
    flat = re.sub(r"\s*\n\s*", " ", p.read_text())
    for m in re.finditer(r'CheckConstraint\((?:[^()]|\([^()]*\))*?name="(ck_[a-z0-9_]+)"', flat):
        print(f"   {p} :: {m.group(1)}")
        found += 1
if not found:
    print("   none")
