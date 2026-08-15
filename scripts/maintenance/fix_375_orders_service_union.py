#!/usr/bin/env python3
"""Resolve #375's orders/service.py conflict: staging's create_order + #375's CDS.

Run from the repo root, mid-merge, after:

    git checkout --theirs backend/app/orders/service.py

WHY NEITHER SIDE IS RIGHT
-------------------------
#375 branched before #376, so its create_order still takes facility_timezone
as a caller-supplied argument — the bug #362 was filed for and #376 fixed by
resolving the timezone from the encounter's own facility. Taking --ours would
reintroduce it.

But #375's create_prescription is the CDS version: allergy gate, override
handling, interaction warnings. Staging has only #374's plain version. Taking
--theirs would drop the whole point of the PR.

So: staging's file, with its create_prescription swapped for #375's, plus the
imports that version needs.
"""
import pathlib
import re
import subprocess
import sys

SVC = pathlib.Path("backend/app/orders/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()
if "<<<<<<<" in text:
    sys.exit("! resolve markers first:  git checkout --theirs backend/app/orders/service.py")

if "check_prescription_item" in text and "facility_timezone: str" not in text:
    print("~ already unioned")
    sys.exit(0)

if "facility_timezone: str" in text:
    sys.exit(
        "! this is #375's copy (create_order still takes facility_timezone).\n"
        "  Run: git checkout --theirs backend/app/orders/service.py  then re-run."
    )

ours = subprocess.run(
    ["git", "show", "HEAD:backend/app/orders/service.py"],
    capture_output=True, text=True, check=True,
).stdout


def grab(src, name):
    """Extract one top-level async def, up to the next top-level def."""
    m = re.search(rf"^async def {name}\(.*?(?=^async def |^def |\Z)", src, re.S | re.M)
    return m.group(0).rstrip() + "\n" if m else None


cds = grab(ours, "create_prescription")
if not cds:
    sys.exit("! could not find create_prescription in #375's copy")
if "check_prescription_item" not in cds:
    sys.exit("! #375's create_prescription has no allergy gate — wrong side?")

old = grab(text, "create_prescription")
if not old:
    sys.exit("! could not find create_prescription in staging's copy")

text = text.replace(old, cds, 1)
print("+ create_prescription replaced with #375's CDS version")

# Imports the CDS version needs that staging's file lacks.
NEEDED = [
    ("from app.allergies.interactions import check_interactions",
     "from app.allergies.service import AllergyConflict, check_prescription_item"),
    ("from app.audit.service import write_audit_log", None),
    ("from app.inventory.models import InventoryItem", None),
]
anchor = "from app.opd.models import Encounter, Visit\n"
if anchor not in text:
    print("! could not find the import anchor — add CDS imports by hand")
else:
    added = []
    block = ""
    for primary, secondary in NEEDED:
        for imp in (primary, secondary):
            if imp and imp not in text:
                block += imp + "\n"
                added.append(imp.split(" import ")[-1])
    if block:
        text = text.replace(anchor, block + anchor, 1)
        print("+ imports:", ", ".join(added))

SVC.write_text(text)
print("\nwrote", SVC)
print("\nfunctions:")
for line in SVC.read_text().splitlines():
    if re.match(r"^(async )?def ", line):
        print("   ", line.split("(")[0], end="")
        print("   <- staging's (no facility_timezone param)"
              if "create_order" in line and "facility_timezone" not in line else "")
