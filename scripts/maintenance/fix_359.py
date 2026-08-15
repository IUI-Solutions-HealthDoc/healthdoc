#!/usr/bin/env python3
"""Fix the three consequences of the 0021/0022 renumber in docs/database-schema.md.

Run from the repo root, on branch docs/renumber-0021-0022-map.

1. order_number_counters had no §3 definition block. The renumber put it in the
   §2 map for the first time (it was never in the map before — Aditya's 0022 is
   a new migration), and spec_check.py requires every mapped table to be defined.
   This is what turned #359 red.
2. The four DPDP tables are labelled (0021, B7) in §3; they are 0022a now.
3. guardian_verification was moved to 0036, but Priyanshu's #353 already holds
   0035/0036/0037. It goes to 0038.
"""
import re
import sys
import pathlib

DOC = pathlib.Path("docs/database-schema.md")
if not DOC.exists():
    sys.exit("run me from the repo root")

text = DOC.read_text()
before = text

# ---------------------------------------------------------------- 1. §3 block
ANCHOR = "### 0021–0026 — Compliance & operations wave"
BLOCK = '''### 0022 — order_number_counters (B6+B3)

**order_number_counters** (0022, B6+B3) — per-facility, per-day order number allocator
```
facility_id UUID NOT NULL → facilities · counter_date date NOT NULL
seq int NOT NULL DEFAULT 0
UNIQUE (facility_id, counter_date)
```
Keyed on `(facility_id, counter_date)`, unlike `accession_counters`, which is global.
Accession numbers are globally unique and carry no facility segment; order numbers are
scoped to the facility that raised them, so two facilities allocating on the same day
must not contend on one row.

`counter_date` is the **business date** — `(now() AT TIME ZONE facilities.timezone)::date`,
never UTC. An order raised at 00:30 IST belongs to that day's sequence, not the previous
one's.

Not gapless, and not required to be — only invoice, receipt and refund numbers carry that
obligation. Allocate with `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` in the same
transaction, for the same reason as `accession_counters`: the first allocation of each day
has no row to lock, so `SELECT ... FOR UPDATE` cannot be used.

Also in 0022: `ALTER orders ADD facility_id UUID NOT NULL → facilities`, backfilled from
`encounters.facility_id`. Denormalized deliberately — the audit layer opts a model in via
`__audit_facility_id_field__`, and reaching through `encounter_id` to find the facility
would make every audited write a join.

---


'''
if "**order_number_counters**" in text:
    print("~ order_number_counters block already present, skipping")
elif ANCHOR not in text:
    sys.exit("! could not find the 0021-0026 wave heading")
else:
    text = text.replace(ANCHOR, BLOCK + ANCHOR, 1)
    print("+ added order_number_counters §3 definition block")

# --------------------------------------------------------------- 2. dpdp 0022a
n = 0
for tbl in ("data_protection_officers", "patient_grievances",
            "data_breach_notifications", "consent_managers"):
    old = f"**{tbl}** (0021, B7)"
    if old in text:
        text = text.replace(old, f"**{tbl}** (0022a, B7)", 1)
        n += 1
if "Also in 0021: `ALTER consent_records" in text:
    text = text.replace("Also in 0021: `ALTER consent_records",
                        "Also in 0022a: `ALTER consent_records", 1)
    n += 1
print(f"~ relabelled {n} DPDP references 0021 -> 0022a")

# ---------------------------------------------------- 3. guardian_verification
old_row = ("| 0036 | guardian_verification | ALTER patients: is_minor, "
           "guardian_verified, guardian_verification_method | B2 (W3) |")
new_row = ("| 0038 | guardian_verification | ALTER patients: is_minor, "
           "guardian_verified, guardian_verification_method | B2 (W3) — 0035/0036/0037 "
           "are taken by #353, which was already written against them |")
if old_row in text:
    text = text.replace(old_row, new_row, 1)
    print("+ guardian_verification 0036 -> 0038")
elif "| 0038 | guardian_verification" in text:
    print("~ guardian_verification already at 0038")
else:
    print("! guardian_verification map row not found — check it by hand")

if "**patients additions** (0022, B2)" in text:
    text = text.replace("**patients additions** (0022, B2)",
                        "**patients additions** (0038, B2)", 1)
    print("+ patients additions (0022, B2) -> (0038, B2)")

# ------------------------------------------------ 3b. record #353's three rows
if "| 0035 | patients_row_version" not in text:
    marker = "| 0034 | ipd_bed_integrity"
    idx = text.find(marker)
    if idx != -1:
        eol = text.find("\n", idx) + 1
        text = text[:eol] + (
            "| 0035 | patients_row_version | ALTER patients: row_version "
            "| B2 (#353) |\n"
            "| 0036 | patient_merge_log_decision_reason | ALTER patient_merge_log: "
            "decision_reason | B2 (#353) |\n"
            "| 0037 | patients_constraint_naming | ALTER patients: constraint names "
            "-> NAMING_CONVENTION | B2 (#353) |\n"
        ) + text[eol:]
        print("+ added map rows for #353's 0035/0036/0037")

if text == before:
    print("\nnothing changed.")
else:
    DOC.write_text(text)
    print("\nwrote docs/database-schema.md")
