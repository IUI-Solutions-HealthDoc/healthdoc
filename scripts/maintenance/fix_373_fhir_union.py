#!/usr/bin/env python3
"""Resolve #373's add/add conflict in abdm/fhir/service.py as a union.

Run from the repo root, mid-merge, AFTER:

    git checkout --theirs backend/app/integrations/abdm/fhir/models.py \\
                          backend/app/integrations/abdm/fhir/service.py

WHY A UNION AND NOT A SIDE
--------------------------
#367 merged fhir/service.py to staging with the encounter-close path:
_build_opd_note_bundle, _build_prescription_bundle, _record_bundle,
build_encounter_close_bundles.

#373 independently created the same file with the discharge path:
_build_discharge_summary_bundle, record_discharge_bundle.

Neither is a superset. Taking --theirs loses discharge bundles (and
admissions/service.py calls record_discharge_bundle, so the app would fail to
import). Taking --ours loses the encounter-close path that already merged.

models.py IS pick-a-side: both declare only FhirBundleTransaction, and
staging's carries the ck_ naming fix, so --theirs is correct there.
"""
import pathlib
import re
import subprocess
import sys

SVC = pathlib.Path("backend/app/integrations/abdm/fhir/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()

if "<<<<<<<" in text:
    sys.exit(
        "! conflict markers still present — run the two `git checkout --theirs`\n"
        "  commands from the docstring first, then re-run this."
    )

if "record_discharge_bundle" in text:
    print("~ already unioned")
    sys.exit(0)

if "build_encounter_close_bundles" not in text:
    sys.exit(
        "! this is not staging's copy — expected build_encounter_close_bundles.\n"
        "  Re-run `git checkout --theirs` on the file first."
    )

# #373's version is the merge's HEAD side.
ours = subprocess.run(
    ["git", "show", "HEAD:backend/app/integrations/abdm/fhir/service.py"],
    capture_output=True, text=True, check=True,
).stdout

m = re.search(r"\ndef _build_discharge_summary_bundle\(.*", ours, re.S)
if not m:
    sys.exit("! could not find _build_discharge_summary_bundle in #373's copy")
discharge_block = m.group(0).rstrip() + "\n"

# Only Admission/Discharge are new — staging's copy already imports uuid,
# datetime/timezone, AsyncSession, FhirBundleTransaction and outbox_service.
IMPORT = "from app.admissions.models import Admission, Discharge\n"
if IMPORT.strip() not in text:
    anchor = "from app.integrations.abdm.fhir.models import FhirBundleTransaction\n"
    if anchor in text:
        text = text.replace(anchor, anchor + IMPORT, 1)
        print("+ import Admission, Discharge")
    else:
        print("! could not place the import — add it by hand")

text = text.rstrip("\n") + "\n\n\n" + discharge_block
SVC.write_text(text)
print("+ appended _build_discharge_summary_bundle and record_discharge_bundle")

print("\nfunctions now in the file:")
for line in SVC.read_text().splitlines():
    if re.match(r"^(async )?def ", line):
        print("   ", line.split("(")[0])
